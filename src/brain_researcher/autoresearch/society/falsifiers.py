"""Falsifier population for the Brain Researcher Society conductor.

Turns the existing scientific-review rule registry
(``configs/br-kg/scientific_review_rule_registry.yaml``) into "ammunition":
for each attack axis we mine the relevant rules' ``description`` (the
natural-language failure mode) and ``detection`` (what evidence to demand) and
compose a prose markdown rubric. ``run_independent_critic`` reads that rubric as
raw text, so the format mirrors the established
``scripts/autoresearch/critic_rubric_*.md`` style (Judgment gate / Completeness
gate / Promotion rule with ``- Fail if`` bullets).

A falsifier may only LOWER confidence in a claim; it can never raise it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cards import NON_EVALUABLE_PROBE_PROVENANCES

logger = logging.getLogger(__name__)

DEFAULT_STRATEGIES: tuple[str, ...] = (
    "site",
    "motion",
    "gsr",
    "atlas",
    "leakage",
    "null",
    "inference",
)

# Methodological-theorem class: a genuine *judgment* failure on these axes is a
# hard reject, because circular analysis / missing nulls / invalid logical
# inference are not consensus dependent (spec section 12, Type C traps have
# definite answers). `inference` covers logical fallacies (reverse inference,
# group-to-individual, in-sample-correlation-as-prediction) that no pipeline
# confound axis catches and that the deterministic checklist cannot enforce.
# ``permutation_null`` (a deterministic L1 gate) joins this class: a result that does
# not exceed its own permutation null is a definite statistical negative, not a matter
# of reviewer consensus → a hard judgment failure → ``rejected``.
HARD_STRATEGIES: frozenset[str] = frozenset(
    {"leakage", "null", "inference", "permutation_null"}
)

# Result-probing strategies judge the RESULT's robustness, not the stated method.
# At least one must run for a claim to achieve ``supported_within_scope`` under the
# no-blind-certification gate (``require_result_probe=True`` on SocietyConductor).
RESULT_PROBE_STRATEGIES: frozenset[str] = frozenset({"confound"})

DEFAULT_REGISTRY_PATH = "configs/br-kg/scientific_review_rule_registry.yaml"

# Rule ids per attack axis, mined from the review rule registry (human-policy
# layer). These are seeds for rubric ammunition, not an assertion that every rule
# is enforced today (many are lifecycle candidates — see harvest notes).
STRATEGY_RULE_IDS: dict[str, tuple[str, ...]] = {
    "site": (
        "MULTISITE_SITE_CONFOUND",
        "HARMONIZATION_OUTSIDE_CV",
        "HARMONIZATION_METHOD_SENSITIVITY",
    ),
    "motion": (
        "MOTION_UNCONTROLLED_GROUP_DIFF",
        "MOTION_REPORTING_GAP",
        "QC_MISSING",
    ),
    "gsr": ("GSR_NO_SENSITIVITY",),
    "atlas": (
        "ROI_MULTIPLE_COMPARISONS",
        "GRAPH_THRESHOLD_NO_SENSITIVITY",
        "SPATIAL_DOMAIN_MISMATCH",
        "ICV_NOT_CONTROLLED",
        "ATLAS_CHOICE_NO_SENSITIVITY",
    ),
    "leakage": (
        "SPLIT_GROUPING_MISMATCH",
        "FEATURE_SELECTION_OUTSIDE_CV",
        "STANDARDIZATION_OUTSIDE_CV",
        "DOUBLE_DIPPING",
    ),
    "null": (
        "UNCORRECTED_WHOLEBRAIN",
        "ROI_MULTIPLE_COMPARISONS",
        "PERMUTATION_EXCHANGEABILITY",
        "BRAINMAP_CORRELATION_NO_SPATIAL_NULL",
        "CLUSTER_FORMING_THRESHOLD_LENIENT",
        "EXTREME_EFFECT",
    ),
    "inference": (
        "REVERSE_INFERENCE",
        "CORRELATION_AS_PREDICTION",
        "FIT_AS_MECHANISM",
        "CLUSTER_LOCALIZATION_OVERCLAIM",
        "SMALL_SAMPLE_STRONG_CLAIM",
        "NO_EXTERNAL_VALIDATION",
    ),
}

# Built-in fallback seeds so a rubric is never empty when the registry file or a
# specific rule is unavailable.
_FALLBACK_SEEDS: dict[str, str] = {
    "site": "the effect is coupled to scanner/site and is neither modeled (site "
    "covariate, per-fold harmonization) nor controlled by restricted permutation",
    "motion": "group mean framewise displacement differs and head motion is neither "
    "modeled as a covariate nor censored",
    "gsr": "main findings are not reported both with and without global signal "
    "regression",
    "atlas": "the result is not shown robust to atlas/parcellation choice and the "
    "data/atlas space alignment is unverified",
    "leakage": "preprocessing, feature selection, or CV grouping leaks information "
    "across folds, or model selection touched the test set",
    "null": "there is no appropriate multiple-comparison correction, spatial null, or "
    "exchangeability-correct permutation, or the effect size is implausibly large "
    "versus the BWAS ceiling (Pearson r ~ 0.4, Marek 2022)",
    "inference": "the conclusion does not follow logically from the analysis — e.g. "
    "reverse inference (reading a cognitive/clinical state from a non-selective region "
    "or network), a group-level result read as an individual-level signature "
    "(ecological/group-to-individual fallacy), an in-sample correlation described as "
    "prediction/biomarker, or model fit asserted as mechanism",
    "permutation_null": "the headline effect does not exceed its own permutation null "
    "(p > 0.05 under the stated exchangeability scheme) — it is statistically "
    "indistinguishable from chance and should not be reported as a positive finding",
    "correction_fragile": "the effect is significant only without correction — it does "
    "not survive multiple-comparison / post-selection correction (a strict corrected "
    "p-value exceeds alpha while the uncorrected p clears it)",
}

# Registry rules whose concern is a MISSING robustness/sensitivity check (a completeness
# gap), NOT a method error. Their `description` is routed to the completeness gate so the
# rule lands at needs_exploration → qualified, and does NOT fire as a hard judgment reject
# on a real claim that merely uses a single common choice (e.g. one atlas) without
# affirmatively stating that robustness was not checked.
_COMPLETENESS_ONLY_RULE_IDS: frozenset[str] = frozenset({"ATLAS_CHOICE_NO_SENSITIVITY"})

# Axis-specific exclusion clauses injected into the rubric's decision-discipline block.
# These NARROW an axis that the harness showed over-fires — they tell the critic what is
# NOT this axis's fallacy, so a legitimate method is not refuted. Society-scoped (the
# shared rule registry is left untouched). See axis_calibration findings.
_AXIS_CAVEATS: dict[str, str] = {
    "inference": (
        "A properly CROSS-VALIDATED, held-out, or external-sample prediction is a "
        "LEGITIMATE out-of-sample result, NOT a CORRELATION_AS_PREDICTION fallacy. Fire "
        "the prediction/biomarker fallacy ONLY when the predictive or biomarker claim "
        "rests on an IN-SAMPLE correlation with NO held-out / cross-validated / external "
        "evaluation reported. The word 'predicts' alone — when the method describes "
        "k-fold CV, a held-out test set, or external replication — is NOT the fallacy."
    ),
}


def load_rule_registry(registry_path: str | Path | None) -> dict[str, dict[str, Any]]:
    """Return ``{rule_id: rule_dict}`` from the review rule registry.

    Returns an empty dict (and logs) on any failure, so falsifiers degrade to
    built-in seeds rather than crashing.
    """
    if not registry_path:
        return {}
    path = Path(registry_path).expanduser()
    if not path.exists():
        logger.warning(
            "society: rule registry not found at %s; using fallback seeds", path
        )
        return {}
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("society: failed to load rule registry %s: %s", path, exc)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for rule in raw.get("rules", []) or []:
        rule_id = rule.get("id")
        if rule_id:
            out[str(rule_id)] = rule
    return out


def build_falsifier_rubric(strategy: str, registry: dict[str, dict[str, Any]]) -> str:
    """Compose the prose markdown rubric for ``strategy``.

    SPECIFICITY is the whole point: a falsifier must refute ONLY when the stated
    method POSITIVELY exhibits its own axis's fallacy, and otherwise PASS. The
    rubric therefore (a) frames the role as a single-axis specialist auditor, not a
    general adversary, (b) defaults both gates to PASS, and (c) phrases every
    failure condition as positive detection ("the method affirmatively does X"),
    never as a double-negative ("does not rule out X") which makes a briefly-stated
    method fail on every axis. The monotonic "only lower confidence" property is
    enforced at synthesis, NOT by priming each critic toward rejection.
    """
    detect_bullets: list[str] = []
    omission_bullets: list[str] = []
    cited: list[str] = []
    for rule_id in STRATEGY_RULE_IDS.get(strategy, ()):
        rule = registry.get(rule_id)
        if not rule:
            continue
        description = str(rule.get("description", "")).strip().rstrip(".")
        detection = str(rule.get("detection", "")).strip().rstrip(".")
        severity = str(rule.get("severity", "WARN"))
        cited.append(f"{rule_id} ({severity})")
        completeness_only_rule = rule_id in _COMPLETENESS_ONLY_RULE_IDS
        if description and not completeness_only_rule:
            detect_bullets.append(f"- the stated method exhibits: {description}.")
        if completeness_only_rule and description:
            # A robustness/sensitivity gap is a COMPLETENESS concern (the analysis is not
            # wrong, a robustness check is simply absent) — route it to the completeness
            # gate so it lands at needs_exploration → qualified, never a judgment reject.
            omission_bullets.append(
                f"- the method performs this analysis but does not establish robustness: "
                f"{description}."
            )
        elif detection:
            omission_bullets.append(
                f"- the method performs this analysis but the artifact shows no {detection}."
            )

    if not detect_bullets:
        seed = _FALLBACK_SEEDS.get(strategy, "a clear, specific flaw on this axis")
        detect_bullets.append(f"- the stated method exhibits: {seed}.")
    if not omission_bullets:
        omission_bullets.append(
            f"- the method clearly relies on this axis but omits the standard {strategy} "
            "safeguard (sensitivity analysis / null model / control) that the procedure requires."
        )

    cited_line = (
        ", ".join(cited) if cited else "(registry unavailable; using built-in seed)"
    )
    lines = [
        f"Brain Researcher Society — `{strategy}` methodology auditor",
        "",
        f"You are a methods reviewer specialised ONLY in the `{strategy}` class of "
        "neuroimaging analysis pitfalls. You are given a claim and its STATED METHOD. "
        f"Your single job: decide whether the stated method COMMITS a `{strategy}` error.",
        "",
        "Decision discipline (read carefully):",
        "- Default to PASS on BOTH gates. A claim is presumed methodologically sound on "
        "this axis unless the STATED METHOD gives positive, specific evidence of a flaw.",
        f"- This is one of several independent single-axis audits; MOST claims are NOT "
        f"vulnerable on the `{strategy}` axis. If the stated method does not involve "
        f"`{strategy}` at all, PASS both gates.",
        "- Do NOT fail because the method is briefly described, because a control is merely "
        '"not mentioned", or because some other axis worries you. Judge ONLY this axis, and '
        "only on what the method AFFIRMATIVELY states.",
        "- If the method explicitly applies the correct safeguard for this axis (e.g. names "
        "the sensitivity analysis, null model, grouping, or correction), PASS.",
        *(
            [f"- EXCLUSION: {_AXIS_CAVEATS[strategy]}"]
            if strategy in _AXIS_CAVEATS
            else []
        ),
        f"Review-rule reference for the `{strategy}` axis: {cited_line}.",
        "",
        "Judgment gate — set passed=false ONLY if the stated method affirmatively does one of:",
        *detect_bullets,
        "Otherwise set judgment.passed=true.",
        "",
        "Completeness gate — set passed=false ONLY if BOTH: the method clearly performs the "
        f"`{strategy}`-governed analysis AND:",
        *omission_bullets,
        "CRITICAL: The input is a brief method SUMMARY, not a full paper methods section. "
        "A summary that omits a preprocessing detail is the EXPECTED NORM, not evidence of "
        "a gap. Do NOT set completeness.passed=false merely because a safeguard is not "
        "mentioned in a brief summary. Only flag when the method text ITSELF affirmatively "
        "describes the absence of a required safeguard (e.g. explicitly says scrubbing was "
        "skipped, or reports uncorrected group differences on this axis).",
        "Otherwise set completeness.passed=true.",
        "",
        "Promotion rule:",
        "- decision=proceed when both gates pass (this axis does not threaten the claim).",
        "- decision=needs_diagnosis when judgment fails (the method commits this axis's error).",
        "- decision=needs_exploration when only completeness fails (the required safeguard is "
        "absent for an analysis that needs it).",
        "",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class FalsifierOutcome:
    """One falsifier's verdict on the claim, normalized for synthesis."""

    strategy: str
    refuted: bool
    degenerate: bool
    judgment_passed: bool
    completeness_passed: bool
    decision: str
    summary: str
    reasons: tuple[str, ...]
    required_actions: tuple[str, ...]
    rubric_ref: str
    hard: bool
    #: How a result-probe verdict was obtained: "commissioned" (society computed it from
    #: raw arrays), "supplied_inconsistent" (computed value contradicts a hand-fed one),
    #: "warrant" (LLM warrant on a missing probe), a non-evaluable probe provenance from
    #: ``NON_EVALUABLE_PROBE_PROVENANCES``, or None (a plain pre-supplied probe).
    provenance: str | None = None
    #: Plausibility verdict of the raw arrays a commissioned probe was computed from:
    #: "clean" / "suspicious" (tamper-EVIDENCE, not tamper-proof) or None (not commissioned).
    integrity: str | None = None


def classify_verdict(verdict: Any) -> tuple[bool, bool]:
    """Return ``(refuted, degenerate)`` for a ``CriticVerdict``.

    * ``refuted`` is re-derived from the two gate booleans (``proceed`` = judgment
      AND completeness passed), NOT from ``decision`` alone, since the LLM can let
      ``decision`` and the gates disagree.
    * ``degenerate`` flags the critic's infra-failure fallback (``"critic
      unavailable: ..."``) or a malformed/empty payload, so a dead critic is not
      counted as a genuine refutation.
    """
    summary = verdict.summary or ""
    raw = verdict.raw_payload or {}
    judgment = verdict.judgment
    completeness = verdict.completeness
    # Degenerate == the critic's infra-failure fallback: it sets a "critic
    # unavailable:" summary and a raw payload WITHOUT the gate structure. Key on the
    # missing gate keys (not on empty reason tuples) so that a genuine both-gates-fail
    # refutation that happens to carry no reasons is still counted as a refutation,
    # rather than silently dropped (which would inflate the claim's status).
    degenerate = (
        summary.startswith("critic unavailable:")
        or "judgment" not in raw
        or "completeness" not in raw
    )
    if degenerate:
        return False, True
    proceed = bool(judgment.passed) and bool(completeness.passed)
    return (not proceed), False


def evaluate_llm_falsifier_axis(
    strategy: str,
    results: dict[str, Any],
    *,
    rubric_path: str,
    critic_runner: Callable[..., Any],
    router: Any,
    critic_model: str | None,
    claim_id: str,
    hard: bool,
    reps: int = 1,
) -> FalsifierOutcome:
    """Run ONE LLM falsifier axis and normalize its verdict to a ``FalsifierOutcome``.

    This is the single source of truth for the LLM-critic path: it is called both by
    ``SocietyConductor.conduct`` (production) and by the adversarial axis-calibration
    harness (``axis_calibration``), so a ``VALIDATED`` calibration verdict reflects the
    exact same ``build_falsifier_rubric → critic → classify_verdict`` path the claim
    adjudication uses.

    ``reps`` (default 1, byte-identical to a single call): the LLM critics are
    nondeterministic, so a single spurious vote — e.g. a HARD ``inference`` axis refuting
    a claim on wording — can swing the whole verdict. When ``reps > 1`` the critic is run
    ``reps`` times and the axis verdict is the **majority of the non-degenerate votes**: a
    refute (and hence, for a hard axis, a ``rejected``) requires a strict majority, so one
    nondeterministic vote cannot drive the status. Degenerate (critic-unavailable) votes
    are excluded from the tally; if every rep is degenerate the axis is reported degenerate
    (unavailable), not a refutation. The vote split is recorded in the outcome summary.
    """
    n = max(1, int(reps))
    votes: list[tuple[bool, bool, Any]] = []
    for i in range(n):
        verdict = critic_runner(
            line_id=f"falsifier_{strategy}:{claim_id}" + ("" if n == 1 else f"#rep{i}"),
            results=results,
            rubric_path=rubric_path,
            router=router,
            model=critic_model,
        )
        refuted_i, degenerate_i = classify_verdict(verdict)
        votes.append((refuted_i, degenerate_i, verdict))

    note = ""
    if n == 1:
        refuted, degenerate, verdict = votes[0]
    else:
        non_degen = [(r, d, v) for (r, d, v) in votes if not d]
        if not non_degen:
            # every rep was infra-degenerate: the axis is unavailable, not a refutation.
            refuted, degenerate, verdict = False, True, votes[-1][2]
            note = f" [majority-vote: all {n} reps degenerate]"
        else:
            n_ref = sum(1 for (r, _d, _v) in non_degen if r)
            refuted = n_ref > len(non_degen) / 2  # strict majority of genuine votes
            degenerate = False
            # Use a representative verdict whose own classification matches the majority,
            # so the emitted gates/reasons are coherent with ``refuted``.
            verdict = next(v for (r, _d, v) in non_degen if r == refuted)
            note = (
                f" [majority-vote: {n_ref}/{len(non_degen)} genuine reps refuted, "
                f"{n - len(non_degen)} degenerate]"
            )

    return FalsifierOutcome(
        strategy=strategy,
        refuted=refuted,
        degenerate=degenerate,
        judgment_passed=bool(verdict.judgment.passed),
        completeness_passed=bool(verdict.completeness.passed),
        decision=verdict.decision,
        summary=(verdict.summary or "") + note,
        reasons=tuple(verdict.judgment.reasons) + tuple(verdict.completeness.reasons),
        required_actions=(
            tuple(verdict.judgment.required_actions)
            + tuple(verdict.completeness.required_actions)
        ),
        rubric_ref=rubric_path,
        hard=hard,
    )


# ---------------------------------------------------------------------------
# L1: deterministic result-probe gates (no LLM critic)
# ---------------------------------------------------------------------------

#: Minimum fraction of the unadjusted effect that must survive residualization.
CONFOUND_RETAINED_THRESHOLD: float = 70.0

#: Significance threshold for the permutation-null gate (a headline p above this does
#: not exceed its own null) and the correction-fragile gate (a strict-corrected p above
#: this means the effect does not survive proper correction). Co-located with the other
#: gate constants for auditability.
PERMUTATION_NULL_ALPHA: float = 0.05
CORRECTION_FRAGILE_ALPHA: float = 0.05

#: Minimum fraction of the post-hoc "best candidate" effect that must survive honest nested
#: leave-fold-out candidate selection. Below this, the headline is largely a selection
#: artifact (circular analysis / double-dipping across the candidate family).
SELECTION_LEAKAGE_RETAINED_THRESHOLD: float = 50.0

#: Small-effect ("trivial") ceiling for the effect-size-floor gate: a claim whose bootstrap CI
#: is reliably POSITIVE (ci_low > 0) yet reliably BELOW this r is statistically significant but
#: practically trivial. 0.1 = Cohen's small-effect boundary.
EFFECT_SIZE_TRIVIAL_R: float = 0.1

#: Minimum fraction of the all-fold mean r that must survive dropping the single best CV fold.
#: Below this, the headline is carried by one fold (non-robust / best-fold cherry-pick).
FOLD_DISPERSION_RETAINED_THRESHOLD: float = 50.0

#: Top-level scorer_payload keys that ONLY the probe commissioner may produce (a society
#: probe DEFINES them — no real scorer computes them), unlike standard inferential statistics
#: (family_block_p, retained_pct, …) which have a legitimate L1 "supplied" path. The conductor
#: strips these from a supplied payload so the corresponding gate can only read a
#: commissioner-injected value — a hand-fed one would be pure laundering surface.
COMMISSIONED_ONLY_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "selection_retained_pct",
        "selection_r_oos",
        "selection_gap",
        "effect_size_ci_low",
        "effect_size_ci_high",
        "fold_dispersion_retained_pct",
    }
)

COMMISSIONED_ONLY_STRATEGY_KEYS: dict[str, frozenset[str]] = {
    "selection_leakage": frozenset({"selection_retained_pct"}),
    "effect_size_floor": frozenset({"effect_size_ci_low", "effect_size_ci_high"}),
    "fold_dispersion": frozenset({"fold_dispersion_retained_pct"}),
}

#: Headline inferential p-value keys, in priority order. ``family_block_p`` /
#: ``permutation_p`` are the whole-result null; ``max_T_p`` / ``post_selection_p`` are
#: strict (multiple-comparison / post-selection corrected) fallbacks used when no raw
#: null p was recorded. NOTE: the bench payload writer may map a ``permutation_p`` value
#: into the ``family_block_p`` slot for KG-lead claims (see run_arm_f.py) — the magnitude
#: is correct so the gate fires correctly; do NOT "fix" that alias away.
_NULL_P_KEYS: tuple[str, ...] = (
    "family_block_p",
    "permutation_p",
    "max_T_p",
    "post_selection_p",
)

#: Strict (corrected) p-value keys for the correction-fragile gate, in priority order.
_STRICT_P_KEYS: tuple[str, ...] = (
    "max_T_post_selection_p",
    "max_T_p",
    "post_selection_p",
)


def _first_present_p(
    payload: dict[str, Any], keys: tuple[str, ...]
) -> tuple[str | None, float | None]:
    """Return ``(key, float_value)`` of the first key present with a non-None,
    numeric value. Mirrors the ``if x is not None`` guard of the confound gate so a
    ``None`` is never coerced via ``float(None)``."""
    for key in keys:
        val = payload.get(key)
        if val is None:
            continue
        try:
            return key, float(val)
        except (TypeError, ValueError):
            continue
    return None, None


def _headline_null_p(payload: dict[str, Any]) -> tuple[str | None, float | None]:
    """First-present headline inferential p-value (see ``_NULL_P_KEYS``)."""
    return _first_present_p(payload, _NULL_P_KEYS)


def _evaluate_permutation_null_gate(results: dict[str, Any]) -> tuple[bool, bool, str]:
    """Deterministic permutation-null gate (hard) — L1, no LLM.

    Returns ``(refuted, probe_missing, reason)``.

    Reads the headline inferential p-value (first present of ``_NULL_P_KEYS``).
    When that p exceeds ``PERMUTATION_NULL_ALPHA`` the result does not exceed its own
    null → hard refute → ``rejected``. When ``p <= alpha`` the gate passes.

    When NO inferential p is present the gate **abstains**: it returns
    ``probe_missing=False`` (NOT ``True``), so the conductor does NOT route to an LLM
    warrant check. A missing null is silence, not a method critique — and there is no
    permutation-null warrant rubric to fall through to. (Routing an absent null to the
    confound warrant is exactly the arm_f bug that mis-landed WPLI at ``qualified``.)
    """
    payload = results.get("scorer_payload") or {}
    key, p = _headline_null_p(payload)
    if p is None:
        return (
            False,
            False,
            "No inferential p-value in scorer_payload; permutation-null gate abstains.",
        )
    if p > PERMUTATION_NULL_ALPHA:
        return (
            True,
            False,
            (
                f"Headline effect does not exceed its own null: {key}={p:.4g} > "
                f"alpha={PERMUTATION_NULL_ALPHA}. The result is statistically "
                "indistinguishable from chance under the stated permutation scheme."
            ),
        )
    return (
        False,
        False,
        f"Headline effect exceeds its null ({key}={p:.4g} <= alpha={PERMUTATION_NULL_ALPHA}).",
    )


def _evaluate_correction_fragile_gate(results: dict[str, Any]) -> tuple[bool, bool, str]:
    """Deterministic correction-fragility gate (completeness-only) — L1, no LLM.

    Returns ``(refuted, probe_missing, reason)``.

    Fires when the UNCORRECTED headline p (``family_block_p``) clears ``alpha`` but a
    STRICT (multiple-comparison / post-selection corrected) p does NOT. This is a
    *completeness-only* refute — the claim survives on its merits but is downgraded to
    ``qualified`` because its significance does not survive proper correction.

    PRINCIPLED ONLY: requires both the uncorrected ``family_block_p`` AND a strict
    corrected p (``_STRICT_P_KEYS``) to be present; abstains otherwise. It never infers
    fragility from effect size alone (that would smuggle oracle-tuned constants into
    production). Always returns ``probe_missing=False`` (abstain, never warrant-route).
    """
    payload = results.get("scorer_payload") or {}
    fam = payload.get("family_block_p")
    if fam is None:
        return (
            False,
            False,
            "No family_block_p in scorer_payload; correction-fragile gate abstains.",
        )
    try:
        fam_p = float(fam)
    except (TypeError, ValueError):
        return (
            False,
            False,
            "family_block_p is not numeric; correction-fragile gate abstains.",
        )
    strict_key, strict_p = _first_present_p(payload, _STRICT_P_KEYS)
    if strict_p is None:
        return (
            False,
            False,
            "No strict (corrected) p-value in scorer_payload; correction-fragile gate abstains.",
        )
    if fam_p <= CORRECTION_FRAGILE_ALPHA and strict_p > CORRECTION_FRAGILE_ALPHA:
        return (
            True,
            False,
            (
                f"Significance is correction-fragile: uncorrected family_block_p={fam_p:.4g} "
                f"<= alpha but strict {strict_key}={strict_p:.4g} > alpha="
                f"{CORRECTION_FRAGILE_ALPHA}. The effect does not survive proper "
                "multiple-comparison / post-selection correction."
            ),
        )
    return (
        False,
        False,
        (
            f"Significance survives correction (family_block_p={fam_p:.4g}, "
            f"{strict_key}={strict_p:.4g})."
        ),
    )


def _evaluate_selection_leakage_gate(results: dict[str, Any]) -> tuple[bool, bool, str]:
    """Deterministic selection-leakage gate (completeness-only) — L1, no LLM.

    Returns ``(refuted, probe_missing, reason)``.

    Fires when the honest nested leave-fold-out-selected effect retains less than
    ``SELECTION_LEAKAGE_RETAINED_THRESHOLD`` of the post-hoc "best candidate" effect — i.e.
    the headline winner's lead is largely a selection artifact (circular analysis /
    double-dipping across the candidate family). A *completeness-only* refute -> ``qualified``.

    PRINCIPLED ONLY: reads ``selection_retained_pct`` which ONLY the commissioner computes
    from the raw candidate matrix (it is a banned answer key, so a hand-fed value is stripped);
    abstains when absent. Always ``probe_missing=False`` (abstain, never warrant-route).
    """
    payload = results.get("scorer_payload") or {}
    val = payload.get("selection_retained_pct")
    if val is None:
        return (
            False,
            False,
            "No selection_retained_pct in scorer_payload; selection-leakage gate abstains.",
        )
    try:
        pct = float(val)
    except (TypeError, ValueError):
        return (
            False,
            False,
            "selection_retained_pct is not numeric; selection-leakage gate abstains.",
        )
    if pct < SELECTION_LEAKAGE_RETAINED_THRESHOLD:
        return (
            True,
            False,
            (
                f"Headline is selection-fragile: honest nested leave-fold-out candidate "
                f"selection retains only {pct:.1f}% of the post-hoc best-candidate effect "
                f"(< {SELECTION_LEAKAGE_RETAINED_THRESHOLD}%). The winner's lead is largely a "
                "selection artifact (circular analysis / double-dipping across the family)."
            ),
        )
    return (
        False,
        False,
        f"Effect survives nested selection (selection_retained_pct={pct:.1f}%).",
    )


def _evaluate_effect_size_floor_gate(results: dict[str, Any]) -> tuple[bool, bool, str]:
    """Deterministic effect-size-floor gate (completeness-only) — L1, no LLM.

    Returns ``(refuted, probe_missing, reason)``.

    Fires (-> qualified) when the headline effect's bootstrap CI is reliably POSITIVE
    (``effect_size_ci_low`` > 0) yet reliably TRIVIAL (``effect_size_ci_high`` < a small-effect
    floor): statistically significant but practically meaningless (the big-N / vanishing-effect
    regime). A *completeness-only* refute — the effect is real, just too small to certify clean
    support.

    PRINCIPLED ONLY: reads the commissioner-computed CI bounds (commissioned-only keys, stripped
    from any supplied payload); abstains when absent. Modest effects at modest N have a WIDE CI
    (ci_high stays above the floor) and do NOT fire, so honest small studies are not penalised.
    """
    payload = results.get("scorer_payload") or {}
    lo = payload.get("effect_size_ci_low")
    hi = payload.get("effect_size_ci_high")
    if lo is None or hi is None:
        return (
            False,
            False,
            "No effect-size CI in scorer_payload; effect-size-floor gate abstains.",
        )
    try:
        ci_low = float(lo)
        ci_high = float(hi)
    except (TypeError, ValueError):
        return (
            False,
            False,
            "effect-size CI is not numeric; effect-size-floor gate abstains.",
        )
    if ci_low > 0.0 and ci_high < EFFECT_SIZE_TRIVIAL_R:
        return (
            True,
            False,
            (
                f"Effect is significant but practically trivial: bootstrap CI "
                f"[{ci_low:.3f}, {ci_high:.3f}] is reliably positive yet entirely below the "
                f"small-effect floor r={EFFECT_SIZE_TRIVIAL_R}. The effect is real but too "
                "small to matter."
            ),
        )
    return (
        False,
        False,
        f"Effect is not reliably-trivial (CI [{ci_low:.3f}, {ci_high:.3f}]).",
    )


def _evaluate_fold_dispersion_gate(results: dict[str, Any]) -> tuple[bool, bool, str]:
    """Deterministic fold-dispersion gate (completeness-only) — L1, no LLM.

    Returns ``(refuted, probe_missing, reason)``.

    Fires (-> qualified) when dropping the single best CV fold collapses the headline effect:
    ``fold_dispersion_retained_pct`` < ``FOLD_DISPERSION_RETAINED_THRESHOLD``. The effect is
    carried by one fold (non-robust / best-fold cherry-pick) rather than holding across the
    sample. A *completeness-only* refute — the effect is real on its best fold but not robust.

    PRINCIPLED ONLY: reads the commissioner-computed retained_pct (a commissioned-only key,
    stripped from any supplied payload); abstains when absent.
    """
    payload = results.get("scorer_payload") or {}
    val = payload.get("fold_dispersion_retained_pct")
    if val is None:
        return (
            False,
            False,
            "No fold_dispersion_retained_pct in scorer_payload; fold-dispersion gate abstains.",
        )
    try:
        pct = float(val)
    except (TypeError, ValueError):
        return (
            False,
            False,
            "fold_dispersion_retained_pct is not numeric; fold-dispersion gate abstains.",
        )
    if pct < FOLD_DISPERSION_RETAINED_THRESHOLD:
        return (
            True,
            False,
            (
                f"Headline is best-fold-driven: dropping the single best CV fold retains only "
                f"{pct:.1f}% of the all-fold mean effect (< {FOLD_DISPERSION_RETAINED_THRESHOLD}%). "
                "The effect is carried by one fold, not robust across the sample."
            ),
        )
    return (
        False,
        False,
        f"Effect is robust across folds (fold_dispersion_retained_pct={pct:.1f}%).",
    )


def _evaluate_confound_gate(results: dict[str, Any]) -> tuple[bool, bool, str]:
    """Deterministic confound gate (L1 / L3).

    Returns ``(refuted, probe_missing, reason)``.

    * **Probe-present path (L1):** reads ``scorer_payload.robustness_probes``.
      If any probe has ``retained_pct < CONFOUND_RETAINED_THRESHOLD`` →
      ``(True, False, reason)`` (hard numeric refute, no LLM).
      All probes pass → ``(False, False, reason)``.

    * **Probe-absent path (L3):** when no ``robustness_probes`` key exists in the
      payload, the deterministic gate cannot assess confound robustness. It signals
      ``probe_missing=True`` so the conductor can commission an LLM warrant check —
      asking whether a residualization probe is warranted given the claim text.
      ``(False, True, reason)``.
    """
    payload = results.get("scorer_payload") or {}
    probes = payload.get("robustness_probes") or []
    if probes:
        for probe in probes:
            retained = probe.get("retained_pct")
            if retained is not None and float(retained) < CONFOUND_RETAINED_THRESHOLD:
                confound = probe.get("confound", "unknown confound")
                return (
                    True,
                    False,
                    (
                        f"Effect retains only {retained}% after residualization against "
                        f"'{confound}' (threshold: {CONFOUND_RETAINED_THRESHOLD}%). "
                        "The claimed construct is largely a proxy for the confound."
                    ),
                )
        return (
            False,
            False,
            (
                f"All robustness probes pass (retained_pct >= {CONFOUND_RETAINED_THRESHOLD}%)"
                " — not confounded."
            ),
        )
    # No probes in payload: cannot assess confound robustness deterministically.
    return (
        False,
        True,
        (
            "No robustness_probes found in scorer_payload; "
            "confound residualization was not performed by the pipeline."
        ),
    )


#: Registry of strategies whose verdict starts deterministically.
#: Each value is ``(results: dict) -> (refuted: bool, probe_missing: bool, reason: str)``.
#: When ``probe_missing=True`` the conductor falls through to an LLM warrant check.
DETERMINISTIC_GATES: dict[str, Callable[[dict[str, Any]], tuple[bool, bool, str]]] = {
    "confound": _evaluate_confound_gate,
    "permutation_null": _evaluate_permutation_null_gate,
    "correction_fragile": _evaluate_correction_fragile_gate,
    "selection_leakage": _evaluate_selection_leakage_gate,
    "effect_size_floor": _evaluate_effect_size_floor_gate,
    "fold_dispersion": _evaluate_fold_dispersion_gate,
}

#: Deterministic gates whose refute lands on the COMPLETENESS axis (needs_exploration
#: → ``qualified``), never the judgment axis. The claim is not *wrong*, it is *not fully
#: certified* (e.g. its significance does not survive strict correction). A gate must
#: not be both hard-judgment and completeness-only (asserted below).
COMPLETENESS_ONLY_GATES: frozenset[str] = frozenset(
    {"correction_fragile", "selection_leakage", "effect_size_floor", "fold_dispersion"}
)

# A hard (judgment) gate and a completeness-only gate are mutually exclusive roles.
# (``permutation_null`` is enrolled in HARD_STRATEGIES at its definition site.)
assert not (HARD_STRATEGIES & COMPLETENESS_ONLY_GATES), (
    "a deterministic gate cannot be both HARD_STRATEGIES and COMPLETENESS_ONLY_GATES"
)

# LLM rubric used when a deterministic gate signals probe_missing=True.
# Only the COMPLETENESS gate is active: we ask whether the probe is *warranted*
# (judgment gate always passes — the stated method is not wrong, the probe is absent).
PROBE_WARRANT_RUBRICS: dict[str, str] = {
    "confound": """\
# Brain Researcher Society — `confound` probe-warrant check (L3)

You are assessing whether a **confound residualization probe is warranted** for this
claim, given that the pipeline did NOT include one in its scorer payload.

**Context:** The pipeline produced a headline effect size (e.g., a predictive accuracy
or correlation) for a behavioral or cognitive outcome. A confound residualization probe
checks whether the effect survives after the outcome target is residualized against a
plausible nuisance construct (e.g., general intelligence, age, head motion).

**Judgment gate** — always PASS (judgment.passed=true). The absence of a probe does
NOT mean the method is wrong; it means completeness is uncertain.

**Completeness gate** — set completeness.passed=false (needs_exploration) ONLY when
BOTH of the following hold:
1. The claim describes a specific behavioral, cognitive, or clinical outcome that is
   plausibly confounded with a well-known nuisance dimension (general intelligence /
   IQ, age, sex, head motion, socioeconomic status, medication, site).
2. The pipeline method does NOT report having residualized against that dimension
   (i.e., no mention of regressing out the confound from the target or the predictions).

If either condition is absent — e.g., the outcome is a pure imaging measure (not
behavioral), or the method explicitly controls for the plausible confound — set
completeness.passed=true (proceed).

**When completeness fails**, populate required_actions with:
  "Commission and run a residualization probe: refit the predictor after residualizing
   the outcome target fold-wise against [the plausible confound]; check retained_pct >= 70%."

Default to PASS on the completeness gate. Only flag when the confound risk is
specific and the control is clearly absent.
""",
}


def build_probe_warrant_rubric(strategy: str) -> str:
    """Return the LLM warrant-check rubric for a probe-missing deterministic strategy."""
    return PROBE_WARRANT_RUBRICS.get(
        strategy,
        f"# Probe warrant check for `{strategy}`\n\n"
        "Judgment gate: always pass.\n"
        "Completeness gate: pass unless the probe is clearly warranted and absent.\n",
    )


def build_deterministic_outcome(
    strategy: str,
    refuted: bool,
    reason: str,
    rubric_ref: str,
    *,
    hard: bool = False,
    completeness_only: bool = False,
) -> FalsifierOutcome:
    """Wrap a deterministic gate result as a ``FalsifierOutcome``.

    The outcome is never degenerate (a deterministic function cannot crash in the
    same way an LLM critic can).

    Two refute-axis modes:

    * **judgment** (default): a refute means the stated method/result is *wrong*
      (``judgment_passed=False``). With ``hard=True`` this routes to ``rejected``;
      otherwise to ``weakened``.
    * **completeness-only** (``completeness_only=True``): a refute means the claim is
      *not fully certified* but not wrong (``judgment_passed=True``,
      ``completeness_passed=False``) — it routes to ``qualified``. Used by gates like
      ``correction_fragile`` where the effect is real but does not survive strict
      correction.
    """
    assert not (hard and completeness_only), (
        "a deterministic gate cannot be both hard-judgment and completeness-only"
    )
    if completeness_only:
        # Refute lands on the completeness axis: the claim survives on its merits but
        # is downgraded (needs_exploration → qualified). Judgment always passes.
        judgment_passed = True
        completeness_passed = not refuted
        decision = "needs_exploration" if refuted else "proceed"
    else:
        judgment_passed = not refuted
        completeness_passed = True
        decision = "needs_diagnosis" if refuted else "proceed"
    return FalsifierOutcome(
        strategy=strategy,
        refuted=refuted,
        degenerate=False,
        judgment_passed=judgment_passed,
        completeness_passed=completeness_passed,
        decision=decision,
        summary=reason,
        reasons=(reason,) if refuted else (),
        required_actions=(),
        rubric_ref=rubric_ref,
        hard=hard,
    )
