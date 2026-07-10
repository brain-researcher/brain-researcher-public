"""NeuroProgram (V1): a declarative research program that lowers onto existing machinery.

A *NeuroProgram* is the thin unifying object above the Gate-2 hypothesis compiler: it binds
a typed :class:`~brain_researcher.autoresearch.society.hypotheses.HypothesisSpecV1` (the
generator), a declared set of review-engine ``constraints`` (rule ids), the
:class:`~brain_researcher.autoresearch.society.cards.ClaimSpecV1` it intends to license, and a
list of ``objectives`` — into one pre-registerable program. ``compile_program`` LOWERS it onto
the pieces that already exist (it builds nothing new of its own):

* design / generators  -> ``compile_design.compile_hypothesis`` + ``HypothesisPlanV1.to_plan_payload``
* constraints          -> ``services.review.rule_engine.get_engine().evaluate_plan(rule_ids=...)``
* fitness ceiling      -> ``calibration.compose_ceilings`` of ``reasoning_mode_ceiling`` +
                          ``claim_structure_ceiling`` (the V-HRL min-law; multiverse survival is
                          the ceiling, never an optimization target)
* commit-before-observe -> ``cards.fingerprint`` over the pre-registration block

OBJECTIVE-SAFETY INVARIANT (load-bearing). A program's ``objectives`` may only target
*validity / robustness / coverage*. Optimizing result MAGNITUDE (effect size, novelty,
significance, association strength) is forbidden — that is automated garden-of-forking-paths,
the exact failure this whole stack guards against. This is enforced three ways: (1) the
:class:`NeuroObjectiveV1` enum has no magnitude member; (2) a field validator rejects any raw
objective string that names a magnitude quantity, with an explicit reason; (3) there is no
optimizer here at all — ``compile_program`` only COMPILES + CHECKS + CEILINGS one declared
program. When/if a search loop is added, its fitness MUST be the ``compose_ceilings`` survival
status (a ceiling), and the search space MUST be the pre-registered, fingerprinted
``design_priors`` — never the magnitude of an observed effect.

Like the rest of ``society``, this module is import-light and service-tier-free: every
service-tier import (the review rule engine, the report-flow gates) is done lazily inside the
function body, mirroring ``compile._default_typecheck``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .calibration import claim_structure_ceiling, compose_ceilings
from .cards import ClaimSpecV1, ClaimStatusV1, ScopeBoundaryV1, fingerprint
from .hypotheses import HypothesisSpecV1, reasoning_mode_ceiling
from .multiverse import CeilingResult


def _utc_now() -> str:
    """ISO-8601 UTC timestamp (matches ``cards._utc_now``)."""
    return datetime.now(timezone.utc).isoformat()


# Raw objective strings naming a *result magnitude* are rejected before enum coercion, with a
# clear reason — so a caller cannot smuggle a p-hacking objective past the typed enum.
_FORBIDDEN_OBJECTIVE_SUBSTRINGS: tuple[str, ...] = (
    "effect_size",
    "effect size",
    "effectsize",
    "max_effect",
    "maximize_effect",
    "novelty",
    "significance",
    "significant",
    "p_value",
    "p-value",
    "pvalue",
    "minimize_p",
    "association",
    "magnitude",
    "z_score",
    "z-score",
)


class NeuroObjectiveV1(str, Enum):
    """Objectives a program may optimize: validity / robustness / coverage ONLY.

    Deliberately has NO ``maximize_effect_size`` / ``maximize_novelty`` member: optimizing the
    magnitude of an observed result over a design space is automated garden-of-forking-paths.
    Magnitude is a *constraint* and a *reported* quantity, never an optimization target.
    """

    maximize_robustness = "maximize_robustness"
    maximize_coverage = "maximize_coverage"
    maximize_reproducibility = "maximize_reproducibility"
    maximize_generalization = "maximize_generalization"
    minimize_compute_cost = "minimize_compute_cost"


class NeuroProgramV1(BaseModel):
    """A declarative research program (the object a NeuroProgram episode is run from)."""

    schema_version: Literal["neuroprogram-v1"] = "neuroprogram-v1"
    program_id: str
    #: The structured generator: which hypothesis the program compiles a design for.
    hypothesis: HypothesisSpecV1
    scope: ScopeBoundaryV1 = Field(default_factory=ScopeBoundaryV1)
    #: Confirmatory claims the program intends to license (commit-before-observe targets).
    claims: list[ClaimSpecV1] = Field(default_factory=list)
    #: Declared review-engine rule ids the compiled plan must satisfy (the constraint set).
    constraints: list[str] = Field(default_factory=list)
    #: Validity/robustness/coverage objectives only — magnitude objectives are rejected.
    objectives: list[NeuroObjectiveV1] = Field(default_factory=list)
    #: Pinned, pre-registered design-search axes for the (DEFERRED) optimizer; passed straight
    #: through to ``compile_hypothesis`` so the program's design priors are recorded + locked.
    design_priors: dict[str, Any] | None = None
    claim_mode: Literal["confirmatory", "exploratory"] = "confirmatory"
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objectives", mode="before")
    @classmethod
    def _reject_magnitude_objectives(cls, value: Any) -> Any:
        for obj in value or []:
            text = str(getattr(obj, "value", obj)).strip().lower()
            for bad in _FORBIDDEN_OBJECTIVE_SUBSTRINGS:
                if bad in text:
                    raise ValueError(
                        f"objective {obj!r} optimizes a result magnitude "
                        f"({bad!r}) — forbidden. Optimizing effect size / novelty / "
                        "significance over a design space is automated garden-of-"
                        "forking-paths. Objectives must target validity, robustness, or "
                        "coverage; magnitude is a constraint and a reported quantity, "
                        "never an optimization target."
                    )
        return value

    def commitment_fingerprint(self) -> str:
        """SHA-256 over the pre-registration block (commit-before-observe).

        Covers the hypothesis, scope, claims, declared constraints, objectives, and pinned
        design priors — everything that must be fixed BEFORE any result is observed, so any
        post-hoc change to the program (or to the axes a future optimizer may search) is
        detectable. Reuses ``cards.fingerprint`` so it is comparable with society/supervisor
        commitment hashes.
        """
        return fingerprint(
            {
                "program_id": self.program_id,
                "hypothesis": self.hypothesis.model_dump(),
                "scope": self.scope.model_dump(),
                "claims": [c.model_dump() for c in self.claims],
                "constraints": sorted(self.constraints),
                "objectives": sorted(o.value for o in self.objectives),
                "design_priors": self.design_priors,
                "claim_mode": self.claim_mode,
            }
        )


class NeuroProgramReportV1(BaseModel):
    """The compiled, gated report for one NeuroProgram (the output of ``compile_program``)."""

    schema_version: Literal["neuroprogram-report-v1"] = "neuroprogram-report-v1"
    program_id: str
    #: The max claim strength this program may license — the composed ceiling, then lowered
    #: by an abstained design (``unresolved``) or a blocking constraint (``ill_typed``).
    status: ClaimStatusV1
    design_status: str  # "compiled" | "abstained"
    dataset_id: str = ""
    task: str = ""
    contrasts: list[dict[str, Any]] = Field(default_factory=list)
    #: The runnable ``{steps:[{tool,params,step_id}]}`` plan (empty when design abstained).
    plan: dict[str, Any] = Field(default_factory=dict)
    #: Declared rule ids that actually ran (declared ∩ engine.rules), or all when none declared.
    constraints_checked: list[str] = Field(default_factory=list)
    constraint_findings: list[dict[str, Any]] = Field(default_factory=list)
    constraints_blocked: bool = False
    #: Declared rule ids NOT present in the engine — surfaced, not silently skipped
    #: (the rule engine fails OPEN on unknown ids, so this closes that gap).
    unknown_constraints: list[str] = Field(default_factory=list)
    ceiling: dict[str, Any] = Field(default_factory=dict)
    objectives: list[str] = Field(default_factory=list)
    #: Per-claim evidence-gate summary, only when ``verify=True`` (opt-in; Neo4j/NiMARE-bound).
    claim_verdicts: dict[str, Any] | None = None
    missing_premises: list[str] = Field(default_factory=list)
    commitment_hash: str
    status_not_ground_truth: bool = True
    generated_at: str = Field(default_factory=_utc_now)


# Strength ladder for the explicit lowering (mirrors calibration._CEILING_STRENGTH; off-ladder
# statuses are most-conservative). Only used to decide whether a lowering actually lowers.
_STRENGTH: dict[ClaimStatusV1, int] = {
    ClaimStatusV1.ill_typed: -2,
    ClaimStatusV1.rejected: -1,
    ClaimStatusV1.conflicting: -1,
    ClaimStatusV1.unresolved: 0,
    ClaimStatusV1.weakened: 1,
    ClaimStatusV1.qualified: 2,
    ClaimStatusV1.supported_within_scope: 3,
}


def _min_status(a: ClaimStatusV1, b: ClaimStatusV1) -> ClaimStatusV1:
    """The more conservative (weaker) of two statuses."""
    return a if _STRENGTH.get(a, -3) <= _STRENGTH.get(b, -3) else b


def _check_constraints(
    plan_payload: dict[str, Any],
    declared: Sequence[str],
) -> tuple[list[str], list[dict[str, Any]], list[str], bool]:
    """Lower the plan into the review engine and evaluate the declared constraint rules.

    Returns ``(checked, findings, unknown, blocked)``. Reuses the SAME engine
    ``neuroclaim_compile`` uses (``get_engine().evaluate_plan``). When ``declared`` is empty,
    ALL plan-mode rules run; otherwise only the declared rules that the engine actually knows
    run, and the unknown declared ids are returned separately (the engine silently skips
    unknown ids, so we report them rather than let a typo'd constraint pass as satisfied).
    """
    if not plan_payload:
        return [], [], [], False

    # Lazy service-tier import — keeps the package import-light + service-free at import time.
    from types import SimpleNamespace

    from brain_researcher.services.review.bundle_builder import build_plan_review_bundle
    from brain_researcher.services.review.rule_engine import get_engine

    engine = get_engine()
    known = {
        rid for rid in (getattr(r, "rule_id", None) for r in getattr(engine, "rules", []))
        if rid
    }
    declared_set = [str(c) for c in (declared or [])]
    unknown = sorted({c for c in declared_set if c not in known})

    if declared_set:
        known_declared = {c for c in declared_set if c in known}
        rule_ids: set[str] | None = known_declared  # empty set => runs nothing (all unknown)
        checked = sorted(known_declared)
    else:
        rule_ids = None  # run every plan-mode rule
        checked = []  # populated from findings' rule ids below for the all-rules case

    # build_plan_review_bundle reads ``plan.steps`` (an attribute), NOT a dict ``["steps"]`` —
    # so the runnable plan dict (from to_plan_payload) is wrapped to expose its keys as attrs.
    bundle = build_plan_review_bundle(SimpleNamespace(**plan_payload))
    findings = engine.evaluate_plan(bundle, rule_ids=rule_ids)
    if not declared_set:
        checked = sorted({getattr(f, "rule_id", "") for f in findings if getattr(f, "rule_id", "")})

    finding_dicts = [
        {
            "rule_id": getattr(f, "rule_id", ""),
            "severity": str(getattr(f, "severity", "")),
            "action": str(getattr(f, "action", "")),
            "message": getattr(f, "message", ""),
            "step_id": getattr(f, "step_id", None),
            "reason_tags": list(getattr(f, "reason_tags", []) or []),
        }
        for f in findings
    ]
    blocked = any(
        str(getattr(f, "severity", "warn")).lower() in ("error", "critical") for f in findings
    )
    return checked, finding_dicts, unknown, blocked


def _run_evidence_gate(
    program: NeuroProgramV1,
    *,
    run_id: str | None,
    backend: Any,
    compile_fn: Any,
) -> dict[str, Any] | None:
    """Opt-in claim-evidence gate over the program's claims (reuses the report-flow gate).

    Best-effort: returns ``None`` when there are no claims or the gate is unavailable. The
    gate itself is the SAME one ``scientific_report_generate`` uses; ``compile_fn`` is
    injectable so tests can run it without a live backend.
    """
    if not program.claims:
        return None
    try:
        from brain_researcher.services.review.claim_evidence_gate import (
            build_claim_evidence_gate,
        )

        return build_claim_evidence_gate(
            program.claims,
            run_id=run_id,
            backend=backend,
            scope=program.scope,
            claim_mode=program.claim_mode,
            compile_fn=compile_fn,
        )
    except Exception as exc:  # pragma: no cover - defensive; the gate is opt-in
        return {"checked": 0, "blocked": False, "error": f"evidence gate unavailable: {exc}"}


def compile_program(
    program: NeuroProgramV1,
    *,
    tasks: Sequence[tuple[str, str, Sequence[str]]] | None = None,
    task_candidate: Any = None,
    model_builder: Callable[[dict[str, dict[str, float]]], dict] | None = None,
    aliases: dict[str, str] | None = None,
    project_root: str = "/app/data",
    verify: bool = False,
    run_id: str | None = None,
    backend: Any = None,
    compile_fn: Any = None,
) -> NeuroProgramReportV1:
    """Lower a NeuroProgram onto existing machinery: compile design, check constraints, ceiling.

    The optimizer is DEFERRED — this compiles, checks, and ceilings ONE declared program; it
    never searches. The pipeline (all reuse, nothing new):

    1. DESIGN: ``compile_hypothesis`` selects a task and resolves typed contrasts (it ABSTAINS
       rather than fabricate a fake contrast); ``to_plan_payload`` emits the runnable plan.
    2. CONSTRAINTS: the plan is lowered into the review rule engine and the declared
       ``constraints`` (rule ids) are evaluated; an error/critical finding blocks.
    3. CEILING: ``compose_ceilings`` of the hypothesis reasoning-mode ceiling and each claim's
       structure ceiling gives the max claim strength the program may license (V-HRL min-law).
    4. LOWERING: an abstained design caps the status at ``unresolved``; a blocking constraint
       caps it at ``ill_typed`` (structural — the same basis ``neuroclaim_compile`` uses).
    5. COMMIT: the pre-registration block is fingerprinted (commit-before-observe).
    6. VERIFY (opt-in): when ``verify=True`` the claims are run through the report-flow
       evidence gate; default off keeps this fast and Neo4j-free.

    Provide ``tasks`` (auto-select) or ``task_candidate`` (explicit); ``model_builder`` is
    injected to stay service-free. Raises ``ValueError`` only if neither task source is given.
    """
    # Lazy import keeps the module's import graph free of the (heavier) compile_design deps
    # at import time, and avoids any import cycle through the package __init__.
    from .compile_design import compile_hypothesis

    plan_obj = compile_hypothesis(
        program.hypothesis,
        task_candidate=task_candidate,
        tasks=tasks,
        model_builder=model_builder,
        design_priors=program.design_priors,
        aliases=aliases,
    )
    design_status = plan_obj.status
    contrasts = [asdict(res) for res in plan_obj.compiled.resolved]

    missing_premises: list[str] = []
    if design_status != "compiled":
        for unresolved in plan_obj.compiled.unresolved:
            reason = unresolved.reason or unresolved.name
            missing_premises.append(f"contrast unresolved ({unresolved.source}): {reason}")
        if not plan_obj.compiled.unresolved:
            missing_premises.append(
                "hypothesis did not resolve to any contrast over the selected task — no "
                "executable design (abstained rather than fabricate a contrast)."
            )

    plan_payload = (
        plan_obj.to_plan_payload(project_root=project_root)
        if design_status == "compiled"
        else {}
    )
    checked, constraint_findings, unknown, constraints_blocked = _check_constraints(
        plan_payload, program.constraints
    )
    if unknown:
        missing_premises.append(
            "declared constraints not present in the review engine (typo or out-of-date "
            f"rule id — NOT silently treated as satisfied): {', '.join(unknown)}"
        )

    # 3. Fitness ceiling (objective-safety): compose the independent structure ceilings.
    ceilings = [reasoning_mode_ceiling(program.hypothesis)]
    ceilings.extend(claim_structure_ceiling(claim) for claim in program.claims)
    composed = compose_ceilings(ceilings)
    status = composed.status

    # 4. Honest lowering. A blocking constraint is structural (same basis as neuroclaim's
    # ill_typed); an abstained design means there is no executable plan to support a claim.
    if constraints_blocked:
        status = _min_status(status, ClaimStatusV1.ill_typed)
        missing_premises.append(
            "blocking constraint finding(s) on the compiled plan — design is type-incoherent."
        )
    elif design_status != "compiled":
        status = _min_status(status, ClaimStatusV1.unresolved)

    claim_verdicts = (
        _run_evidence_gate(program, run_id=run_id, backend=backend, compile_fn=compile_fn)
        if verify
        else None
    )

    return NeuroProgramReportV1(
        program_id=program.program_id,
        status=status,
        design_status=design_status,
        dataset_id=plan_obj.dataset_id,
        task=plan_obj.task,
        contrasts=contrasts,
        plan=plan_payload,
        constraints_checked=checked,
        constraint_findings=constraint_findings,
        constraints_blocked=constraints_blocked,
        unknown_constraints=unknown,
        ceiling=composed.model_dump(),
        objectives=[o.value for o in program.objectives],
        claim_verdicts=claim_verdicts,
        missing_premises=missing_premises,
        commitment_hash=program.commitment_fingerprint(),
    )


# The SocietyConductor's ceiling spine ranks statuses via `_LADDER.index(...)` over
# {rejected, weakened, qualified, supported_within_scope} ONLY, so an off-ladder program
# verdict (ill_typed / unresolved) must be clamped before it joins the spine — else `_rank`
# raises. Structural-fail / off-ladder verdicts clamp to the most conservative ladder rung
# the spine accepts (`weakened`); `rejected` is never synthesized here (it needs a positive
# refutation, not a mere program cap). The full verdict is preserved in `inputs` for audit.
_PROGRAM_AXIS_LADDER_SAFE: dict[ClaimStatusV1, ClaimStatusV1] = {
    ClaimStatusV1.supported_within_scope: ClaimStatusV1.supported_within_scope,
    ClaimStatusV1.qualified: ClaimStatusV1.qualified,
    ClaimStatusV1.weakened: ClaimStatusV1.weakened,
}


def program_ceiling_axis(report: NeuroProgramReportV1) -> CeilingResult:
    """A composable ceiling axis from a compiled program, for the conductor's V-HRL spine.

    ``report.status`` already folds the structural ceiling AND the honest lowering (abstained
    design -> unresolved, blocking constraint -> ill_typed). This wraps it as a
    :class:`CeilingResult` clamped to the conductor's ladder so a pre-registered program that
    failed structurally caps the claim at ``weakened`` rather than crashing the rank-based
    spine. The full verdict (incl. the un-clamped status, ``constraints_blocked``, and the
    pre-registration ``commitment_hash``) is preserved in ``inputs`` for audit / harder gating.
    """
    safe = _PROGRAM_AXIS_LADDER_SAFE.get(report.status, ClaimStatusV1.weakened)
    return CeilingResult(
        status=safe,
        display=f"neuroprogram:{report.program_id}",
        rationale=(
            f"pre-registered program status={report.status.value} "
            f"(design={report.design_status}, constraints_blocked={report.constraints_blocked}); "
            f"commitment={report.commitment_hash[:12]}"
        ),
        inputs={
            "program_id": report.program_id,
            "program_status": report.status.value,
            "design_status": report.design_status,
            "constraints_blocked": report.constraints_blocked,
            "commitment_hash": report.commitment_hash,
        },
    )


__all__ = [
    "NeuroObjectiveV1",
    "NeuroProgramV1",
    "NeuroProgramReportV1",
    "compile_program",
    "program_ceiling_axis",
    "MultiverseExecResult",
    "MultiverseRunner",
    "NeuroProgramEpisodeResult",
    "reduce_zmaps_to_summary_df",
    "run_neuroprogram_episode",
    "make_fitlins_multiverse_runner",
]


# ======================================================================================
# Autonomous NeuroProgram EPISODE — given a hypothesis, chain compile -> optimize ->
# execute multiverse -> bounded claim card, in commit-before-observe order.
#
# This is the autonomous loop: it turns the NeuroProgram tools into one capability. Multiverse
# EXECUTION is heavy + service/shell-shaped, so it is an INJECTED ``pipeline_runner`` seam — the
# `neuroprogram-real-fmri` skill (or a prod adapter) supplies the real fitlins runner; tests
# inject a fake returning a canned summary table. Objective-safety is preserved STRUCTURALLY by
# the step order: both commitment fingerprints (program + chosen design family) are frozen BEFORE
# the runner is ever invoked, and the family/contrast bindings are fail-closed.
# ======================================================================================


@dataclass(frozen=True)
class MultiverseExecResult:
    """What a ``pipeline_runner`` returns after EXECUTING a committed design family.

    ``summary_df`` is a pandas DataFrame in the ``build_multiverse_robustness_report`` schema
    (columns ``contrast, metric, region_id`` [str], ``model_id, variant_id, value, pct_active,
    z_thr``). ``executed_variant_ids`` MUST reflect what ACTUALLY ran (not echo the committed
    ids) — the fail-closed superset check depends on it.
    """

    summary_df: Any
    executed_variant_ids: tuple[str, ...]
    multiverse_run_id: str


#: A runner executes the committed multiverse and returns its results. Injected so the heavy
#: fitlins/nilearn/S3 path stays out of the import graph and out of hermetic tests.
MultiverseRunner = Callable[["NeuroProgramReportV1", Any], MultiverseExecResult]


class NeuroProgramEpisodeResult(BaseModel):
    """The outcome of one autonomous NeuroProgram episode (hypothesis -> bounded claim)."""

    schema_version: Literal["neuroprogram-episode-v1"] = "neuroprogram-episode-v1"
    program_id: str
    status: ClaimStatusV1
    #: the effective claim mode after any optimizer-forced downgrade (degenerate prior / unknown
    #: constraint / no eligible family force 'exploratory').
    claim_mode: str = "confirmatory"
    design_status: str
    ran_pipeline: bool
    report: dict[str, Any]
    optimize: dict[str, Any] | None = None
    claim_card: dict[str, Any] | None = None
    multiverse_binding_status: str | None = None
    multiverse_run_id: str | None = None
    family_binding: dict[str, Any] | None = None
    commitment_hashes: dict[str, str] = Field(default_factory=dict)
    missing_premises: list[str] = Field(default_factory=list)
    status_not_ground_truth: bool = True
    generated_at: str = Field(default_factory=_utc_now)


def reduce_zmaps_to_summary_df(
    stage: str,
    variants: Sequence[str],
    contrast: str,
    session: str | None,
    atlas_path: str,
    z_thr: float = 2.3,
):
    """Parcellate each variant's contrast z-map into a per-region ``summary_df`` (for real runners).

    Lifted from the ``neuroprogram-real-fmri`` skill. Uses event-independent atlas parcellation;
    ``region_id`` is emitted as **str** (the ``build_multiverse_robustness_report`` picker compares
    region ids as strings). nilearn/numpy/pandas are lazy-imported (heavy; never at module top).
    """
    import glob
    import re as _re

    import numpy as np
    import pandas as pd
    from nilearn.image import load_img, resample_to_img

    def _norm(x: str) -> str:  # fitlins sanitizes contrast entities (e.g. drops '_') — match tolerantly
        return _re.sub(r"[^a-z0-9]", "", str(x).lower())

    want = _norm(contrast)
    rows: list[dict] = []
    means: dict[str, float] = {}
    for vid in variants:
        import os as _os
        allz = glob.glob(f"{stage}/out_{vid}/**/*stat-z_statmap.nii.gz", recursive=True)
        found = [f for f in allz
                 if (m := _re.search(r"contrast-([A-Za-z0-9]+)", f)) and _norm(m.group(1)) == want]
        if not found:
            raise FileNotFoundError(
                f"no stat-z map for contrast {contrast!r} in {stage}/out_{vid} "
                f"(found contrasts: {sorted({(_re.search(r'contrast-([A-Za-z0-9]+)', f) or [None, ''])[1] for f in allz})})")
        # Prefer the DATASET-LEVEL (group) map over per-subject maps: fitlins emits both
        # 'ses-..._contrast-X_stat-z' (group) and 'sub-NN_..._contrast-X_stat-z' (per subject)
        # for the same contrast; the multiverse robustness must summarise the GROUP result.
        group = [f for f in found if not _os.path.basename(f).startswith("sub-")]
        zimg = load_img((group or found)[0])
        z = zimg.get_fdata()
        atlas = resample_to_img(atlas_path, zimg, interpolation="nearest",
                                force_resample=True, copy_header=True)
        alab = np.asarray(atlas.get_fdata()).astype(int)
        means[vid] = float(np.nanmean(z[np.isfinite(z) & (z != 0)]))
        for lab in np.unique(alab):
            if lab == 0:
                continue
            m = (alab == lab) & np.isfinite(z)
            if not m.any():
                continue
            vals = z[m]
            rows.append(dict(model_id="multiverse", variant_id=vid, contrast=contrast,
                             metric="mean_z", region_id=str(int(lab)),
                             value=float(np.mean(vals)),
                             pct_active=float(np.mean(vals > z_thr)), z_thr=z_thr))
    return pd.DataFrame(rows), means


#: HRF basis -> (BIDS StatsModel Convolve Model, Derivative, Dispersion). NB: 'fir' is a valid
#: BIDS-StatsModel basis but is not reliably supported by the nilearn fitlins estimator — such a
#: variant simply fails to fit and is DROPPED by the runner, which then trips the fail-closed
#: committed-vs-executed family check (honest, not a bug).
_HRF_CONVOLVE = {
    "canonical": ("spm", False, False),
    "derivs": ("spm", True, True),
    "glover": ("glover", False, False),
    "fir": ("fir", False, False),
}
_CONFOUND_X_6 = ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z", "cosine*"]
_CONFOUND_X_24 = ["trans_*", "rot_*", "cosine*"]


def _build_variant_model(report: NeuroProgramReportV1, decision_points: dict, *,
                         subjects: Sequence[str], session: str | None) -> dict:
    """Build a fitlins BIDS Stats Model for one committed variant: base contrasts from the report,
    HRF / confounds / high-pass from the variant's decision points. Mirrors the validated
    neuroprogram-real-fmri skill model template."""
    convolve_model, deriv, disp = _HRF_CONVOLVE.get(
        str(decision_points.get("hrf_basis", "canonical")), ("spm", False, False))
    conf_x = _CONFOUND_X_6 if str(decision_points.get("confounds", "6mot")) == "6mot" else _CONFOUND_X_24
    try:
        hp_cut = int(decision_points.get("high_pass", 128))
    except (TypeError, ValueError):
        hp_cut = 128
    contrasts = [
        {"Name": c["name"], "ConditionList": list(c["condition_list"]),
         "Weights": list(c["weights"]), "Test": c.get("test", "t")}
        for c in report.contrasts
    ]
    inp: dict = {"subject": list(subjects), "task": [report.task]}
    if session:
        inp["session"] = [session]
    return {
        "Name": f"{report.dataset_id}-{decision_points.get('variant_id', 'mv')}",
        "BIDSModelVersion": "1.0.0", "Input": inp,
        "Nodes": [
            {"Name": "run_level", "Level": "Run", "GroupBy": ["run", "subject", "session"],
             "Transformations": {"Transformer": "pybids-transforms-v1", "Instructions": [
                 {"Name": "Factor", "Input": ["trial_type"]},
                 {"Name": "Convolve", "Model": convolve_model, "Input": ["trial_type.*"],
                  "Derivative": deriv, "Dispersion": disp}]},
             "Model": {"X": [1, "trial_type.*", *conf_x], "Type": "glm",
                       "Options": {"HighPassFilterCutoff": hp_cut}},
             "Contrasts": contrasts},
            # DummyContrasts passes the run-level contrasts up to the dataset level; an explicit
            # empty Contrasts here makes fitlins' second-level model do spec['contrasts'][0] on an
            # empty list -> IndexError (the data-level node must auto-aggregate the run contrasts).
            {"Name": "data_level", "Level": "Dataset", "GroupBy": ["contrast", "session"],
             "Model": {"X": [1], "Type": "glm"}, "DummyContrasts": {"Test": "t"}},
        ],
    }


def make_fitlins_multiverse_runner(
    *,
    bids_dir: str,
    derivatives_dir: str,
    atlas_path: str,
    subjects: Sequence[str],
    stage_dir: str,
    space: str = "MNI152NLin2009cAsym",
    session: str | None = "test",
    n_cpus: int = 2,
    z_thr: float = 2.3,
) -> "MultiverseRunner":
    """The REAL default multiverse runner: executes the committed design family with fitlins and
    reduces the z-maps to a robustness summary table. Heavy (fitlins subprocess + nilearn) and
    environment-bound — all imports are lazy. Returns a runner closure for run_neuroprogram_episode.
    A variant that fails to fit is DROPPED (not echoed as executed), so the fail-closed
    committed-vs-executed check caps the binding honestly.
    """
    def _runner(report: NeuroProgramReportV1, opt: Any) -> "MultiverseExecResult":
        import json
        import os
        import subprocess
        from pathlib import Path

        from .binding_ids import canonical_multiverse_run_id

        primary = report.contrasts[0]["name"] if report.contrasts else None
        Path(stage_dir, "models").mkdir(parents=True, exist_ok=True)
        tf_home = os.environ.get("TEMPLATEFLOW_HOME", f"{stage_dir}/templateflow")
        Path(tf_home).mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "MPLBACKEND": "Agg", "TEMPLATEFLOW_HOME": tf_home}

        executed: list[str] = []
        ids = list(opt.winner_variant_ids)
        for i, dp in enumerate(opt.winner_variants):
            # the committed id is in winner_variant_ids (aligned by position) — NOT inside the
            # decision-points dict; use it so executed_variant_ids matches the committed family.
            vid = str(ids[i]) if i < len(ids) else f"mv{i}"
            model = _build_variant_model(report, {**dp, "variant_id": vid},
                                         subjects=subjects, session=session)
            mpath = f"{stage_dir}/models/model-{vid}.json"
            Path(mpath).write_text(json.dumps(model))
            cmd = ["fitlins", bids_dir, f"{stage_dir}/out_{vid}", "dataset",
                   "-d", derivatives_dir, "-m", mpath, "--space", space,
                   "--estimator", "nilearn", "--participant-label", *list(subjects),
                   "-w", f"{stage_dir}/work_{vid}", "--n-cpus", str(n_cpus)]
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if proc.returncode == 0:
                executed.append(vid)

        if not executed:
            raise RuntimeError(
                f"fitlins multiverse produced no executed variants for {report.dataset_id}/"
                f"{report.task} (all {len(opt.winner_variants)} committed variants failed to fit — "
                "check the staged bids/derivatives, the atlas/space, and the HRF bases).")
        summary_df, _means = reduce_zmaps_to_summary_df(
            stage_dir, executed, primary, session, atlas_path, z_thr=z_thr)
        run_id = canonical_multiverse_run_id(
            dataset_id=report.dataset_id, task=report.task, variant_ids=executed)
        return MultiverseExecResult(summary_df=summary_df,
                                    executed_variant_ids=tuple(executed), multiverse_run_id=run_id)

    return _runner


def _episode_claim(program: NeuroProgramV1, claim: ClaimSpecV1 | None, *, contrast: str | None):
    """Derive the claim to verify, stamping ``extra['contrast']`` to bind robustness (fail-closed:
    a mismatch yields an ``unbound`` multiverse axis, not a crash)."""
    if claim is not None:
        extra = dict(claim.extra)
        if contrast:
            extra["contrast"] = contrast
        return claim.model_copy(update={"extra": extra})
    if program.claims:
        base = program.claims[0]
        extra = dict(base.extra)
        if contrast:
            extra["contrast"] = contrast
        return base.model_copy(update={"extra": extra})
    return ClaimSpecV1(
        claim_id=f"{program.program_id}:claim",
        claim_text=program.hypothesis.statement,
        scope_boundary=program.scope,
        confirmatory=(program.claim_mode == "confirmatory"),
        extra={"contrast": contrast} if contrast else {},
    )


def _completed_stop():
    """A minimal 'pipeline completed' StopArtifact so the spine starts from supported_within_scope
    and the ceilings (program / multiverse / family) do the bounding."""
    from brain_researcher.autoresearch.state_contract import StopArtifact

    return StopArtifact(
        line_id="neuroprogram_episode", session_id="neuroprogram_episode",
        final_status="completed", stop_reason="completed", total_cycles=1, stall_count=0,
        elapsed_seconds=0.0, last_score=1.0, scorer_name="neuroprogram", last_scorer_payload_path=None,
    )


def run_neuroprogram_episode(
    program: NeuroProgramV1,
    *,
    pipeline_runner: MultiverseRunner,
    tasks: Sequence[tuple[str, str, Sequence[str]]] | None = None,
    task_candidate: Any = None,
    model_builder: Callable[[dict[str, dict[str, float]]], dict] | None = None,
    claim: ClaimSpecV1 | None = None,
    k_variants: int = 6,
    n_candidates: int = 8,
    search: str = "grid",
    seed: int = 0,
    weights: dict[str, float] | None = None,
    efficiency_fn: Callable[[dict], float] | None = None,
    constraint_fn: Callable[[dict], bool] | None = None,
    falsifier_outcomes: Sequence[Any] | None = None,
    project_root: str = "/app/data",
) -> NeuroProgramEpisodeResult:
    """Run one autonomous NeuroProgram episode: hypothesis -> bounded ClaimCardV1.

    Commit-before-observe ORDER (the load-bearing objective-safety property):
      1. ``compile_program`` — freezes the program ``commitment_hash`` (first commit). If the
         design ABSTAINS, short-circuit: no pipeline is ever run on a non-existent design.
      2. ``optimize_design_family`` — freezes the chosen design family
         (``family_commitment_fingerprint``; second commit).
      3. ``pipeline_runner(report, optimize_result)`` — EXECUTES the committed family. Invoked
         ONLY here, strictly AFTER both commits; the episode never re-optimizes on its results.
      4. ``resolve_committed_family`` — fail-closed: the executed family must be a SUPERSET of the
         committed one, else the robustness binding is capped (selection-laundering guard).
      5. ``build_multiverse_robustness_report`` -> ``MultiverseProfile.from_robustness_report``.
      6. ``synthesize_claim_card`` — bounded by the program + multiverse + family ceilings
         (contrast/family bindings both fail-closed).

    ``pipeline_runner`` is REQUIRED and injected (real fitlins execution is heavy + environment-
    bound — the ``neuroprogram-real-fmri`` skill provides the real runner; tests inject a fake).
    """
    # Lazy imports (avoid the conductor<->neuroprogram cycle + keep heavy deps out of import time).
    from .cards import lock_commitment
    from .conductor import synthesize_claim_card
    from .multiverse import MultiverseProfile
    from .optimize import (
        make_constraint_fn,
        make_count_efficiency_fn,
        optimize_design_family,
        resolve_committed_family,
    )

    # 1. COMPILE — first commit.
    report = compile_program(
        program, tasks=tasks, task_candidate=task_candidate, model_builder=model_builder,
        project_root=project_root,
    )
    hashes = {"program": report.commitment_hash}
    if report.design_status != "compiled":
        # No executable design -> never run a pipeline; honest abstain bounded by the program.
        return NeuroProgramEpisodeResult(
            program_id=program.program_id, status=report.status,
            claim_mode=program.claim_mode,
            design_status=report.design_status, ran_pipeline=False,
            report=report.model_dump(mode="json"), missing_premises=list(report.missing_premises),
            commitment_hashes=hashes,
        )

    primary_contrast = report.contrasts[0]["name"] if report.contrasts else None
    episode_claim = _episode_claim(program, claim, contrast=primary_contrast)

    # 2. OPTIMIZE — second commit (locks the chosen design family).
    eff = efficiency_fn or make_count_efficiency_fn()
    cons = constraint_fn or make_constraint_fn(
        builder_arg=report.plan.get("steps", [{}])[0].get("params", {}).get("contrasts", {}),
        dataset_id=report.dataset_id, task=report.task,
        hypothesis_id=program.hypothesis.hypothesis_id,
        declared_constraints=program.constraints, project_root=project_root,
    )
    opt = optimize_design_family(
        program, efficiency_fn=eff, constraint_fn=cons, k_variants=k_variants,
        n_candidates=n_candidates, search=search, seed=seed, weights=weights,
        unknown_constraints=report.unknown_constraints,
    )
    hashes["family"] = opt.commitment_hash
    # Propagate an optimizer-forced downgrade into the claim: optimize_design_family drops to
    # 'exploratory' for a degenerate prior, an unknown declared constraint, or no eligible family.
    # If we left the claim 'confirmatory', a forced-exploratory design could still yield a
    # confirmatory-labelled card — so downgrade the claim, which caps claim_structure_ceiling.
    if opt.claim_mode == "exploratory" and episode_claim.confirmatory:
        episode_claim = episode_claim.model_copy(update={"confirmatory": False})

    # 3. EXECUTE — only now, strictly after both commits.
    exec_result = pipeline_runner(report, opt)

    # 4. fail-closed family reconciliation (executed must be a superset of the committed family).
    family_ceiling = resolve_committed_family(opt.winner_variant_ids, exec_result.executed_variant_ids)

    # 5. robustness -> profile.
    from brain_researcher.core.analysis.multiverse_robustness_report import (
        build_multiverse_robustness_report,
    )

    rpt = build_multiverse_robustness_report(
        exec_result.summary_df, contrast=primary_contrast, metric="mean_z")
    rpt.setdefault("input", {})["contrast"] = primary_contrast
    profile = MultiverseProfile.from_robustness_report(rpt, run_id=exec_result.multiverse_run_id)

    # 6. synthesize the bounded claim card (program + multiverse + family ceilings).
    commitment = lock_commitment(episode_claim, [], {})
    card = synthesize_claim_card(
        episode_claim, commitment, _completed_stop(), list(falsifier_outcomes or []),
        hypothesis=program.hypothesis, multiverse_profiles=[profile],
        multiverse_run_id=exec_result.multiverse_run_id, neuroprogram_report=report,
        extra_ceilings=[family_ceiling],
    )
    cal = card.extra.get("calibration", {})
    return NeuroProgramEpisodeResult(
        program_id=program.program_id, status=card.status, claim_mode=opt.claim_mode,
        design_status=report.design_status,
        ran_pipeline=True, report=report.model_dump(mode="json"),
        optimize=opt.model_dump(mode="json"), claim_card=card.model_dump(mode="json"),
        multiverse_binding_status=cal.get("multiverse_binding_status"),
        multiverse_run_id=exec_result.multiverse_run_id,
        family_binding=family_ceiling.model_dump(), commitment_hashes=hashes,
    )
