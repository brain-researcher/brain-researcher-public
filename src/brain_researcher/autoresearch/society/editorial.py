"""LLM-backed Editor Board + settlement jury runners (HTML sections 08/09).

The economy layer (:mod:`society.economy`) ships the *mechanism* — :class:`JuryPanel`,
:class:`EditorBoard`, the calibration x confidence aggregation, the H2 tie invariant —
but the conductor never actually convened real voters (a deliberate "no real editor
agents = theater" stub). This module supplies the two LLM-backed runners that produce
those votes from a claim card + the evidence bundle, mirroring
:func:`brain_researcher.autoresearch.critic.run_independent_critic`:

* :func:`run_jury_votes` — seats ``n_jurors`` jurors, each emitting a vote on the
  ambiguous settlement.
* :func:`run_editor_board_votes` — seats one editor per board ``seat``.

Both build a prompt from the claim card + the JSON-safe ``results`` the falsifiers
already judge, ask the model for an evidential ``vote`` (one of
:class:`ClaimStatusV1` MINUS the structural ``ill_typed``), a ``confidence`` in
``[0, 1]``, and a short ``rationale``, parse strict JSON, and return typed votes.

CRITICAL — calibration is SYSTEM-SUPPLIED, never self-reported.
``calibration`` (historical accuracy) is the aggregation weight's other factor
(``weight = calibration x confidence``). It is a *prior* passed in by the caller
(default :data:`DEFAULT_CALIBRATION`), NOT something the model returns: a voter must
not be able to inflate its own aggregation weight by claiming to be well-calibrated.
The model's response is parsed for ``vote``/``confidence``/``rationale`` ONLY; any
``calibration`` field a model tries to smuggle in is ignored.

On an LLM / parse failure the runner degrades safely — it returns a low-confidence
``unresolved`` vote for that voter (and logs), never crashing the settlement.

Nothing here imports the service tier; the router is injected.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from brain_researcher.core.contracts.llm_router import LLMRouterProtocol

from .cards import ClaimCardV1, ClaimStatusV1

if TYPE_CHECKING:  # annotations only; the runtime import is lazy (avoid import cycle)
    from .calibration_store import CalibrationStore
    from .economy import EditorVote, JurorVote

logger = logging.getLogger(__name__)

# The evidential statuses a voter may choose. ``ill_typed`` is a structural-only
# verdict (produced solely by ``neuroclaim_compile``); the evidence/decision layer
# must NEVER emit it, so it is excluded from the allowed vote vocabulary.
_VOTE_CHOICES: tuple[ClaimStatusV1, ...] = (
    ClaimStatusV1.supported_within_scope,
    ClaimStatusV1.qualified,
    ClaimStatusV1.weakened,
    ClaimStatusV1.conflicting,
    ClaimStatusV1.rejected,
    ClaimStatusV1.unresolved,
)
_VOTE_VALUES: frozenset[str] = frozenset(v.value for v in _VOTE_CHOICES)

#: System-supplied default calibration prior (historical accuracy). Conventions, not
#: tuned. NEVER taken from the model's response (see module docstring).
DEFAULT_CALIBRATION = 0.7

#: The confidence assigned to the safe fallback ``unresolved`` vote on an
#: LLM / parse failure — deliberately low so a dead voter never dominates.
_FALLBACK_CONFIDENCE = 0.1

DEFAULT_JURY_MODEL = "claude-sonnet-4-6"
DEFAULT_EDITOR_MODEL = "claude-sonnet-4-6"


def _extract_json_payload(text: str) -> dict[str, Any]:
    """Parse a strict-JSON object from a model response (mirrors critic.py)."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("editorial vote response must be a JSON object")
    return payload


def _coerce_vote(value: Any) -> ClaimStatusV1:
    """Map a model-returned status string onto an allowed evidential vote.

    Unknown / out-of-vocabulary / structural (``ill_typed``) values degrade to
    ``unresolved`` so a malformed vote can never inject ``ill_typed`` or fabricate
    support.
    """
    raw = str(value or "").strip().lower()
    if raw in _VOTE_VALUES:
        return ClaimStatusV1(raw)
    return ClaimStatusV1.unresolved


def _coerce_confidence(value: Any) -> float:
    """Clamp a model-returned confidence into ``[0, 1]``; default 0 on garbage."""
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    if conf != conf:  # NaN
        return 0.0
    return max(0.0, min(1.0, conf))


def _evidence_bundle(claim_card: ClaimCardV1, evidence: dict[str, Any]) -> dict[str, Any]:
    """Assemble the JSON-safe context a voter judges from — ANTI-ANCHORING.

    The holistic voter must judge the CLAIM ON ITS MERITS. We deliberately WITHHOLD
    the "looks-fine" signals that empirically anchor the voter toward
    ``supported_within_scope`` (confirmed: the same juror votes a reverse-inference
    trap ``rejected`` 3/3 on the bare claim but caves to ``supported`` once shown an
    all-clear): the naive ``synthesized_status``, ``survived_checks``, the
    ``pipeline_summary`` ("completed / passing score"), and the
    ``falsification_budget_spent`` ("N critics, 0 refuted"). Falsifiers may only ADD
    genuine concerns (``failed_checks`` / ``next_required_evidence``), never present an
    all-clear the judge anchors on. Voters reason ONLY from this — no hidden
    chain-of-thought or agent rationale.
    """
    return {
        "claim": {
            "claim_id": claim_card.claim_id,
            "claim_text": claim_card.claim_text,
            "scope_boundary": claim_card.scope_boundary.model_dump(),
        },
        # ONLY genuine concerns raised by the falsifier population — never the
        # survived/all-clear, the naive synthesized status, or the pipeline "it worked".
        "raised_concerns": list(claim_card.failed_checks),
        "next_required_evidence": list(claim_card.next_required_evidence),
        "results": evidence,
    }


def _build_prompt(
    *,
    role: str,
    seat_or_juror: str,
    claim_card: ClaimCardV1,
    evidence: dict[str, Any],
) -> str:
    schema = {
        "vote": "|".join(v.value for v in _VOTE_CHOICES),
        "confidence": "number in [0,1]",
        "rationale": "short string",
    }
    bundle_json = json.dumps(
        _evidence_bundle(claim_card, evidence), indent=2, sort_keys=True, default=str
    )
    schema_json = json.dumps(schema, indent=2, sort_keys=True)
    return f"""You are a {role} ({seat_or_juror}) adjudicating a scientific claim.

Cast ONE independent, evidential vote on the claim's status, judging the claim ON ITS
MERITS. Scrutinise it for methodological fallacies (reverse inference, circular
analysis / double-dipping, multiverse/pipeline fragility, site/motion/GSR confounds,
leakage, uncorrected mass-univariate testing). Any concerns already raised are listed
under `raised_concerns`; their ABSENCE is NOT evidence the claim is sound — judge
independently.

You must judge ONLY from the claim and the concerns/results below. Do not assume access
to any prior verdict, chain-of-thought, agent rationale, or hidden context. Status is an
EDITORIAL/evidential verdict, NOT ground truth (`supported_within_scope` != true,
`rejected` != false). Reject claims resting on a methodological fallacy; qualify/weaken
real-but-fragile claims; mark genuinely open questions `unresolved`.

Choose exactly one `vote` from the allowed set. Do NOT invent a `calibration` or any
weighting — your historical accuracy is tracked by the system independently of this
vote and cannot be self-reported.

Claim + evidence bundle:
{bundle_json}

Return ONLY a JSON object matching this shape:
{schema_json}
"""


def _parse_one_vote(text: str) -> tuple[ClaimStatusV1, float, str]:
    """Parse a single model response into (vote, confidence, rationale)."""
    payload = _extract_json_payload(text)
    vote = _coerce_vote(payload.get("vote"))
    confidence = _coerce_confidence(payload.get("confidence"))
    rationale = str(payload.get("rationale") or "").strip()
    return vote, confidence, rationale


def _calibration_for(index: int, calibrations: Sequence[float] | None) -> float:
    """System-supplied calibration prior for voter ``index``.

    Pulled from the injected ``calibrations`` sequence when long enough, else the
    :data:`DEFAULT_CALIBRATION` prior. NEVER read from the model response.

    Defensive: a caller-supplied calibration that is non-numeric, NaN, or infinite
    must not crash the whole settlement nor silently become the maximum weight — it
    falls back to :data:`DEFAULT_CALIBRATION` (mirroring :func:`_coerce_confidence`).
    A valid finite number is clamped into ``[0, 1]``.
    """
    if calibrations is not None and index < len(calibrations):
        try:
            value = float(calibrations[index])
        except (TypeError, ValueError):
            return DEFAULT_CALIBRATION
        if not math.isfinite(value):  # NaN or +/-inf -> degrade to default, not max
            return DEFAULT_CALIBRATION
        return max(0.0, min(1.0, value))
    return DEFAULT_CALIBRATION


def _calibration_prior(
    *,
    voter_id: str,
    index: int,
    calibrations: Sequence[float] | None,
    calibration_store: "CalibrationStore | None",
) -> float:
    """Resolve the SYSTEM-supplied calibration prior for one voter.

    Precedence: an injected :class:`CalibrationStore` (earned per-voter historical
    accuracy) > the positional ``calibrations`` sequence > :data:`DEFAULT_CALIBRATION`.
    A store with no record for ``voter_id`` yields exactly :data:`DEFAULT_CALIBRATION`
    by construction (its zero-data prior mean), so wiring a fresh store is behaviour-
    preserving. The non-finite hardening of :func:`_calibration_for` is applied to the
    store value too, so a corrupt store can never crash the settlement.

    This is SYSTEM-supplied like the old prior: the value comes from the store / the
    caller, NEVER from the model's response (the no-self-inflation invariant).
    """
    if calibration_store is not None:
        return _calibration_for(0, [calibration_store.calibration(voter_id)])
    return _calibration_for(index, calibrations)


def run_jury_votes(
    *,
    claim_card: ClaimCardV1,
    evidence: dict[str, Any],
    router: LLMRouterProtocol,
    model: str = DEFAULT_JURY_MODEL,
    n_jurors: int = 3,
    calibrations: Sequence[float] | None = None,
    calibration_store: "CalibrationStore | None" = None,
) -> list[JurorVote]:
    """Seat ``n_jurors`` LLM jurors and return their typed votes (HTML section 09).

    Each juror gets the claim card + the falsifier evidence bundle and returns an
    evidential ``vote`` + ``confidence`` + ``rationale`` (strict JSON). The
    ``calibration`` weight is SYSTEM-SUPPLIED and never read from the model: when a
    ``calibration_store`` is injected each juror's prior is its *earned* historical
    accuracy (``store.calibration(juror_id)``); otherwise it comes from the positional
    ``calibrations`` sequence, defaulting to :data:`DEFAULT_CALIBRATION`. (A fresh
    store with no record yields exactly :data:`DEFAULT_CALIBRATION`, so wiring one is
    behaviour-preserving.) On an LLM / parse failure the juror degrades to a
    low-confidence ``unresolved`` vote — the settlement never crashes.
    """
    from .economy import JurorVote  # local import: avoid import cycle at module load

    votes: list[JurorVote] = []
    for i in range(max(0, int(n_jurors))):
        juror_id = f"juror_{i + 1}"
        calibration = _calibration_prior(
            voter_id=juror_id,
            index=i,
            calibrations=calibrations,
            calibration_store=calibration_store,
        )
        prompt = _build_prompt(
            role="settlement juror",
            seat_or_juror=juror_id,
            claim_card=claim_card,
            evidence=evidence,
        )
        try:
            response = router.route_chat(
                prompt=prompt,
                model_hint=model,
                task_type="classification",
                strict_json=True,
            )
            vote, confidence, rationale = _parse_one_vote(response.text)
        except Exception as exc:
            logger.warning("settlement juror %s failed: %s", juror_id, exc)
            vote, confidence, rationale = (
                ClaimStatusV1.unresolved,
                _FALLBACK_CONFIDENCE,
                f"juror unavailable: {exc}",
            )
        votes.append(
            JurorVote(
                juror_id=juror_id,
                vote=vote,
                confidence=confidence,
                calibration=calibration,
                rationale=rationale or None,
            )
        )
    return votes


def run_editor_board_votes(
    *,
    claim_card: ClaimCardV1,
    evidence: dict[str, Any],
    router: LLMRouterProtocol,
    model: str = DEFAULT_EDITOR_MODEL,
    seats: Sequence[str] = (
        "stats_methodology",
        "neuroimaging_validity",
        "scientific_significance",
    ),
    calibrations: Sequence[float] | None = None,
    calibration_store: "CalibrationStore | None" = None,
) -> list[EditorVote]:
    """Seat one LLM editor per board ``seat`` and return their votes (HTML section 09).

    Each seated editor gets the claim card + the falsifier evidence bundle and
    returns an evidential ``vote`` + ``confidence`` + ``rationale`` (strict JSON).
    The ``calibration`` weight is SYSTEM-SUPPLIED and never read from the model — the
    editor "bets authority, not credit", and cannot self-inflate its aggregation
    weight. When a ``calibration_store`` is injected each seat's prior is its *earned*
    historical accuracy (``store.calibration(seat)`` — keyed on the STABLE ``seat``,
    not the per-episode ``member_id``); otherwise it comes from the positional
    ``calibrations`` sequence, defaulting to :data:`DEFAULT_CALIBRATION`. On an
    LLM / parse failure the seat degrades to a low-confidence ``unresolved`` vote.
    """
    from .economy import EditorVote  # local import: avoid import cycle at module load

    votes: list[EditorVote] = []
    for i, seat in enumerate(seats):
        member_id = f"editor_{seat}"
        calibration = _calibration_prior(
            voter_id=str(seat),
            index=i,
            calibrations=calibrations,
            calibration_store=calibration_store,
        )
        prompt = _build_prompt(
            role="editor board member",
            seat_or_juror=seat,
            claim_card=claim_card,
            evidence=evidence,
        )
        try:
            response = router.route_chat(
                prompt=prompt,
                model_hint=model,
                task_type="classification",
                strict_json=True,
            )
            vote, confidence, rationale = _parse_one_vote(response.text)
        except Exception as exc:
            logger.warning("editor board seat %s failed: %s", seat, exc)
            vote, confidence, rationale = (
                ClaimStatusV1.unresolved,
                _FALLBACK_CONFIDENCE,
                f"editor unavailable: {exc}",
            )
        votes.append(
            EditorVote(
                member_id=member_id,
                seat=str(seat),
                vote=vote,
                confidence=confidence,
                calibration=calibration,
                rationale=rationale or None,
            )
        )
    return votes


__all__ = [
    "DEFAULT_CALIBRATION",
    "DEFAULT_EDITOR_MODEL",
    "DEFAULT_JURY_MODEL",
    "run_editor_board_votes",
    "run_jury_votes",
]
