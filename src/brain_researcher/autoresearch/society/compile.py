"""``neuroclaim_compile`` — the internal claim/plan correctness kernel (orchestrator).

Composes existing Brain Researcher machinery into one pass that gates the agent's
OWN claims before it asserts them, returning a transparent, provenance-carrying
report instead of a summary:

    typecheck (deterministic, crisp)  ->  evidence (probabilistic, soft)
        ->  MANDATORY sensitivity sweep  ->  named-uncertainty vector + 'sorries'

Two honesty levels are never blurred:

* a *structural* failure yields the crisp ``ill_typed`` status
  (``verdict_basis == "structural"``) and SHORT-CIRCUITS — no evidential verdict is
  attempted for a type-incoherent claim (e.g. an EEG dataset fed to an fMRI GLM);
* otherwise the soft *evidential* ladder is used (``verdict_basis == "evidential"``),
  and **no evidential verdict ships without a sensitivity result** — if it does not
  survive a conservative evidence bar it is flagged threshold-fragile.

The two largest neuroimaging-specific uncertainties (coordinate->region and
task->ontology mapping) surface as honest, unresolved *sorries* rather than
fabricated numbers — surfacing a missing premise beats a polished derivation.

Nothing is imported from the service tier at module load; the typecheck and
provenance helpers are lazy-imported (and injectable), so the package stays
import-light and the unit tests never touch Neo4j or the rule registry.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from .cards import ScopeBoundaryV1
from .cards import ClaimStatusV1
from .evidence_backend import (
    DEFAULT_PROFILE,
    STRICT_PROFILE,
    EvidenceVerdict,
    ProbabilisticEvidenceBackend,
    resolve_backend,
)
from .evidence_quality import score_evidence_quality
from .uncertainty import NamedUncertainty, build_uncertainty


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    return "claim:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _light_formalize(claim_text: str) -> dict[str, Any]:
    """A trivial structural stand-in when the backend gives no normalized claim.

    Deliberately dumb — real subject/relation/object resolution belongs to the KG
    entity resolver (surfaced via ``EvidenceVerdict.normalized_claim``); this only
    guarantees ``formalized_claim`` is never empty.
    """
    return {"raw": claim_text, "subject": None, "relation": None, "object": None}


# Relations that assert cognitive *engagement* / directional involvement of a region
# — the "P(region | cognition)" claim shape that forward activation cannot establish.
_REVERSE_INFERENCE_MARKERS: tuple[str, ...] = (
    "engages",
    "engaged in",
    "involved in",
    "is involved",
    "involvement",
    "mediates",
    "mediated by",
    "underlies",
    "underlying",
    "subserves",
    "responsible for",
    "supports",
    "recruited",
    "necessary for",
    "implements",
)


def _is_reverse_inference_claim(claim_text: str) -> bool:
    """True if the claim asserts cognitive engagement of a region (reverse-inference shape)."""
    t = (claim_text or "").lower()
    return any(m in t for m in _REVERSE_INFERENCE_MARKERS)


class TypecheckResult(BaseModel):
    """Deterministic structural verdict on the (optional) analysis plan."""

    checked: bool  # was a plan available to typecheck?
    well_typed: bool
    findings: list[dict[str, Any]] = Field(default_factory=list)
    ill_typed_reasons: list[str] = Field(default_factory=list)
    skipped_reason: str = ""


class SensitivityResult(BaseModel):
    """Whether the evidential verdict survives a conservative evidence bar."""

    ran: bool
    default_profile: str = ""
    default_status: ClaimStatusV1 | None = None
    strict_profile: str = ""
    strict_status: ClaimStatusV1 | None = None
    verdict_survives: bool | None = None
    note: str = ""


class NeuroClaimReportV1(BaseModel):
    """The compiled, provenance-carrying report for one claim (the tool's output)."""

    schema_version: Literal["neuroclaim-report-v1"] = "neuroclaim-report-v1"
    claim_id: str
    claim_text: str
    formalized_claim: dict[str, Any] = Field(default_factory=dict)
    scope: ScopeBoundaryV1
    status: ClaimStatusV1
    verdict_basis: Literal["structural", "evidential"]
    typecheck: TypecheckResult
    evidence_verdict: EvidenceVerdict | None = None
    uncertainty: NamedUncertainty
    sensitivity: SensitivityResult | None = None
    contradictions: list[str] = Field(default_factory=list)
    missing_premises: list[str] = Field(default_factory=list)
    source_spans: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None
    reproducible_query: dict[str, Any] = Field(default_factory=dict)
    backend: str = ""
    run_id: str | None = None
    status_not_ground_truth: bool = True
    generated_at: str = Field(default_factory=_utc_now)


TypecheckFn = Callable[[Any, ScopeBoundaryV1], TypecheckResult]


def _default_typecheck(plan: Any, scope: ScopeBoundaryV1) -> TypecheckResult:
    """Run the existing plan review rule engine; map error/critical -> ill_typed.

    With no plan there is nothing structural to check — this is recorded as a
    *skipped* (not a passed) typecheck so the absence becomes a 'sorry', never a
    silent green light.
    """
    if plan is None:
        return TypecheckResult(
            checked=False,
            well_typed=True,
            skipped_reason="no plan supplied — pipeline type-coherence not checked",
        )
    # Lazy: keep the package import-light and service-tier-free at import time.
    from brain_researcher.services.review.bundle_builder import build_plan_review_bundle
    from brain_researcher.services.review.rule_engine import get_engine

    bundle = build_plan_review_bundle(plan)
    findings = get_engine().evaluate_plan(bundle)
    errs = [
        f
        for f in findings
        if str(getattr(f, "severity", "warn")).lower() in ("error", "critical")
    ]
    return TypecheckResult(
        checked=True,
        well_typed=not errs,
        findings=[
            {
                "rule_id": getattr(f, "rule_id", ""),
                "severity": str(getattr(f, "severity", "")),
                "message": getattr(f, "message", ""),
                "reason_tags": list(getattr(f, "reason_tags", []) or []),
            }
            for f in findings
        ],
        ill_typed_reasons=[
            f"{getattr(f, 'rule_id', '')}: {getattr(f, 'message', '')}" for f in errs
        ],
    )


def _resolve_backend_arg(
    backend: ProbabilisticEvidenceBackend | str | None,
) -> ProbabilisticEvidenceBackend:
    if backend is None or isinstance(backend, str):
        return resolve_backend(backend)
    return backend


def _run_sensitivity(
    backend: ProbabilisticEvidenceBackend,
    claim_text: str,
    scope: ScopeBoundaryV1,
    default_verdict: EvidenceVerdict,
) -> SensitivityResult:
    """Re-verify under the conservative profile; does the verdict survive?"""
    try:
        strict = backend.verify(claim_text, scope, profile=STRICT_PROFILE)
    except Exception as exc:  # pragma: no cover - defensive
        return SensitivityResult(ran=False, note=f"sensitivity run failed: {exc}")
    survives = strict.status == default_verdict.status
    return SensitivityResult(
        ran=True,
        default_profile=DEFAULT_PROFILE.name,
        default_status=default_verdict.status,
        strict_profile=STRICT_PROFILE.name,
        strict_status=strict.status,
        verdict_survives=survives,
        note=(
            "verdict unchanged under conservative evidence"
            if survives
            else "verdict changed under conservative evidence — threshold-fragile"
        ),
    )


def _run_provenance(
    claims_provenance: list[dict[str, Any]] | None,
    run_provenance_index: Any,
) -> dict[str, Any] | None:
    """Best-effort run-bound provenance gate (only when both inputs are present)."""
    if not claims_provenance or run_provenance_index is None:
        return None
    from brain_researcher.services.review.claim_provenance import (
        ClaimProvenance,
        validate_claim_provenance,
    )

    claims = [ClaimProvenance(**c) for c in claims_provenance]
    verdicts = validate_claim_provenance(claims, run_provenance_index, require_full=False)
    return {
        "checked": len(verdicts),
        "unsupported": [v.claim_id for v in verdicts if not v.ok],
        "verdicts": [v.model_dump() for v in verdicts],
    }


def neuroclaim_compile(
    claim_text: str,
    *,
    claim_id: str | None = None,
    scope: ScopeBoundaryV1 | None = None,
    plan: Any = None,
    run_id: str | None = None,
    claims_provenance: list[dict[str, Any]] | None = None,
    run_provenance_index: Any = None,
    backend: ProbabilisticEvidenceBackend | str | None = None,
    extraction_confidence: float | None = None,
    extraction_source: str = "caller",
    run_sensitivity: bool = True,
    multiverse: dict[str, Any] | None = None,
    typecheck_fn: TypecheckFn | None = None,
) -> NeuroClaimReportV1:
    """Compile one neuroscience claim into a transparent, gated report.

    Args:
        claim_text: the natural-language claim.
        scope: the :class:`ScopeBoundaryV1` it is asserted within.
        plan: an optional analysis plan; when present it is typechecked and an
            error/critical finding makes the claim ``ill_typed`` (short-circuit).
        run_id / claims_provenance / run_provenance_index: optional run-bound
            provenance gate (claims may not cite artifacts a run never produced).
        backend: a backend instance, a name, or ``None`` (resolve from env).
        extraction_confidence: the caller's extractor confidence — recorded as its
            own uncertainty dim and NEVER folded into the association probability.
        run_sensitivity: when False, the verdict ships with a loud "robustness
            unknown" caveat instead of a sensitivity result.
        multiverse: an optional multiverse-robustness profile (``active_frac`` /
            ``sign_consistency`` / ``effect_size_stability``) feeding ONLY the
            methodological ``evidence_quality`` axis (never the association
            probability); a fragile profile caps quality.
        typecheck_fn: injectable for tests (default runs the real rule engine).
    """
    claim_id = claim_id or _slug(claim_text)
    scope = scope or ScopeBoundaryV1()
    backend_obj = _resolve_backend_arg(backend)
    typecheck = (typecheck_fn or _default_typecheck)(plan, scope)

    # 1. Structural gate. An ill-typed claim never reaches the evidence layer.
    if not typecheck.well_typed:
        unc = build_uncertainty(
            extraction_confidence=extraction_confidence,
            extraction_source=extraction_source,
        )
        return NeuroClaimReportV1(
            claim_id=claim_id,
            claim_text=claim_text,
            formalized_claim=_light_formalize(claim_text),
            scope=scope,
            status=ClaimStatusV1.ill_typed,
            verdict_basis="structural",
            typecheck=typecheck,
            evidence_verdict=None,
            uncertainty=unc,
            sensitivity=None,
            missing_premises=list(typecheck.ill_typed_reasons) + unc.sorries(),
            reproducible_query={"typecheck": "rule_engine.evaluate_plan(build_plan_review_bundle(plan))"},
            backend=getattr(backend_obj, "name", ""),
            run_id=run_id,
        )

    # 2. Evidence (lenient default profile).
    evidence = backend_obj.verify(claim_text, scope, profile=DEFAULT_PROFILE)

    # 2b. Reverse-inference guard (panel: forbid forward-only "engages" claims from
    #     reaching supported). Forward-convergence evidence shows P(activation | term-
    #     studies), NOT P(cognition | region); a cognitive-engagement claim backed only
    #     by it cannot reach clean support (Poldrack 2006 base-rate fallacy). Cap it.
    reported_status = evidence.status
    reverse_caveat: str | None = None
    if (
        evidence.inference == "forward_convergence"
        and _is_reverse_inference_claim(claim_text)
        and evidence.status == ClaimStatusV1.supported_within_scope
    ):
        reported_status = ClaimStatusV1.qualified
        reverse_caveat = (
            "reverse inference not established: forward-convergence evidence only "
            "(P(region|cognition) != P(cognition|region), Poldrack 2006) — capped "
            "supported_within_scope -> qualified"
        )

    # 3. Mandatory sensitivity — no evidential verdict ships without it.
    if run_sensitivity:
        sensitivity = _run_sensitivity(backend_obj, claim_text, scope, evidence)
    else:
        sensitivity = SensitivityResult(
            ran=False, note="sensitivity disabled by caller — verdict robustness UNKNOWN"
        )

    # 4. The named uncertainty vector. The two big neuro-specific mapping
    #    uncertainties are left unresolved (-> sorries) rather than fabricated.
    #    ``evidence_quality`` is scored from METHODOLOGICAL signals only (study count,
    #    evidence balance, inference tier, sensitivity-flip, optional multiverse
    #    robustness) — never the association probability or extraction confidence, so
    #    the no-laundering invariant holds (see society/evidence_quality.py).
    quality = score_evidence_quality(
        n_supporting=evidence.n_supporting,
        n_conflicting=evidence.n_conflicting,
        inference=evidence.inference,
        verdict_survives=sensitivity.verdict_survives if sensitivity.ran else None,
        multiverse=multiverse,
    )
    uncertainty = build_uncertainty(
        association_p=evidence.association_probability,
        association_source=f"{evidence.backend}.confidence",
        extraction_confidence=extraction_confidence,
        extraction_source=extraction_source,
        evidence_quality=quality.value,
        evidence_source=f"{evidence.backend}.method_quality",
        coordinate_to_region=evidence.region_confidence,
        coordinate_source=evidence.region_source,
        task_to_ontology=evidence.term_confidence,
        task_source=evidence.term_source,
        notes={"evidence_quality": quality.rationale},
    )

    # 5. Missing premises ('sorries') — uncertainty + skipped typecheck + fragility.
    missing = list(uncertainty.sorries())
    if not typecheck.checked:
        missing.append(typecheck.skipped_reason or "pipeline type-coherence not checked (no plan)")
    if sensitivity.ran and sensitivity.verdict_survives is False:
        missing.append(
            "verdict does not survive the conservative evidence bar "
            f"({_status_value(sensitivity.default_status)} -> "
            f"{_status_value(sensitivity.strict_status)}) — threshold-fragile"
        )
    if not sensitivity.ran:
        missing.append("sensitivity sweep not run — verdict robustness unknown")
    if reverse_caveat:
        missing.append(reverse_caveat)

    # 6. Optional run-bound provenance gate.
    provenance = _run_provenance(claims_provenance, run_provenance_index)

    return NeuroClaimReportV1(
        claim_id=claim_id,
        claim_text=claim_text,
        formalized_claim=evidence.normalized_claim or _light_formalize(claim_text),
        scope=scope,
        status=reported_status,
        verdict_basis="evidential",
        typecheck=typecheck,
        evidence_verdict=evidence,
        uncertainty=uncertainty,
        sensitivity=sensitivity,
        contradictions=evidence.conflicting_refs,
        missing_premises=missing,
        source_spans=evidence.supporting_refs,
        provenance=provenance,
        reproducible_query=evidence.reproducible_query,
        backend=evidence.backend,
        run_id=run_id,
    )


def _status_value(status: ClaimStatusV1 | None) -> str:
    return status.value if status is not None else "?"


def certify_report(
    report: NeuroClaimReportV1,
    *,
    corpus_version: str = "",
    extra_inputs: dict[str, Any] | None = None,
    ledger: Any = None,
) -> Any:
    """OPT-IN: turn a compiled report into a NeuroProof audit certificate.

    This is a thin, explicit bridge — :func:`neuroclaim_compile` does NOT call it,
    so default compile behavior is unchanged. Callers who want a tamper-evident,
    replayable certificate over a report invoke this directly. When ``ledger`` is a
    :class:`society.proof_ledger.ProofLedger`, the certificate is also appended.

    The certificate freezes the report's input/query/rule digests + backend and the
    supplied ``corpus_version``; it certifies reproducibility and tamper-evidence of
    the audit basis, NOT empirical truth (see :mod:`society.proof_ledger`).
    """
    # Lazy import keeps the compile module's import surface unchanged.
    from .proof_ledger import build_certificate

    cert = build_certificate(
        report, corpus_version=corpus_version, extra_inputs=extra_inputs
    )
    if ledger is not None:
        ledger.append(cert)
    return cert
