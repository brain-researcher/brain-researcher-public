"""Swappable probabilistic-evidence backend for ``neuroclaim_compile``.

The scientific-association layer is *not* reinvented here — it is delegated behind
a single :class:`ProbabilisticEvidenceBackend` protocol so the engine is swappable:

* :class:`KgVerifyBackend` (default, always available) wraps the existing
  ``services.br_kg.query_service.verify_hypothesis`` — the KG verifier already
  aligns supporting vs conflicting evidence and emits a verdict.
* :class:`NeuroLangBackend` computes the Neurosynth-style forward inference
  ``P(activation@region | term)`` and its base-rate lift through NeuroLang's
  probabilistic-Datalog solver over a coordinate corpus. NeuroLang pins
  ``python>=3.12`` and an incompatible ``pandas``/``nibabel``/``nilearn`` line, so it
  runs OUT-OF-PROCESS in a dedicated venv (``BR_NEUROLANG_PYTHON``) via
  :mod:`neurolang_worker`; this backend prepares the facts (it has nimare + grounding)
  and ships them as JSON. When the corpus or the venv is absent it declares itself
  unavailable, so :func:`resolve_backend` transparently falls back to the KG backend.

The service tier is imported lazily *inside* methods (and is injectable for tests),
so this module — like the rest of ``autoresearch`` — has no import-time service
dependency.

An :class:`EvidenceProfile` parameterises the strength bar so the same claim can be
re-verified under a lenient vs a conservative evidence rule — the runnable basis for
the mandatory sensitivity sweep in ``compile.py``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .cards import ClaimStatusV1, ScopeBoundaryV1, classify_kg_verdict
from .grounding import (
    RegionResolution,
    TermResolution,
    region_surface_aliases,
    resolve_region,
    resolve_term,
)

logger = logging.getLogger(__name__)


class EvidenceBackendUnavailable(RuntimeError):
    """Raised when a requested backend cannot serve a query (triggers fallback)."""


class EvidenceProfile(BaseModel):
    """A named strength bar for evidence aggregation (the sensitivity knob).

    ``strictness`` maps to the KG verifier's evidence threshold
    (``high_recall`` 0.18 / ``balanced`` 0.35 / ``conservative`` 0.55); a NeuroLang
    backend would map it onto its ``reliable_study`` rule set (cluster-FWE vs
    voxel-FWE, n>=30 vs power-based).
    """

    name: str
    strictness: str = "high_recall"
    min_evidence_score: float | None = None
    note: str = ""


#: Lenient default — a broad evidence net.
DEFAULT_PROFILE = EvidenceProfile(
    name="default",
    strictness="high_recall",
    note="lenient recall (evidence threshold ~0.18) — broad net",
)
#: Strict counterpart for the sensitivity sweep: the analog of voxel-FWE /
#: power-based ``reliable_study`` — does the verdict survive a higher bar?
STRICT_PROFILE = EvidenceProfile(
    name="strict",
    strictness="conservative",
    note="conservative evidence only (threshold ~0.55) — voxel-FWE/power-based analog",
)


class EvidenceVerdict(BaseModel):
    """A backend's evidential verdict on one claim (never structural/ill_typed)."""

    status: ClaimStatusV1
    backend: str
    profile: str = DEFAULT_PROFILE.name
    association_probability: float | None = None
    confidence: float | None = None
    normalized_claim: dict[str, Any] | None = None
    #: How the association was derived, e.g. "forward_convergence" (NiMARE ALE) —
    #: used by the compiler's reverse-inference guard. "" = unknown direction.
    inference: str = ""
    #: Grounding confidences (coordinate->region, task->ontology) + their sources, fed
    #: into the report's named-uncertainty vector. None when not grounded (e.g. kg).
    region_confidence: float | None = None
    term_confidence: float | None = None
    region_source: str = ""
    term_source: str = ""
    n_supporting: int = 0
    n_conflicting: int = 0
    supporting_refs: list[str] = Field(default_factory=list)
    conflicting_refs: list[str] = Field(default_factory=list)
    #: The literal backend call + args, so the answer is re-runnable.
    reproducible_query: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


@runtime_checkable
class ProbabilisticEvidenceBackend(Protocol):
    """The one seam between neuroclaim and whatever computes association evidence."""

    name: str

    def available(self) -> bool: ...

    def verify(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict: ...


def _refs(items: Any, *, cap: int = 20) -> list[str]:
    """Pull short, stable references out of evidence dicts for the verdict."""
    out: list[str] = []
    for it in (items or [])[:cap]:
        if isinstance(it, dict):
            ref = (
                it.get("publication_id")
                or it.get("doi")
                or it.get("study_id")
                or it.get("id")
                or it.get("title")
            )
            out.append(
                str(ref) if ref is not None else json.dumps(it, default=str)[:120]
            )
        else:
            out.append(str(it))
    return out


def _summary_int(summary: dict[str, Any], key: str, fallback: Any) -> int:
    try:
        return int(summary.get(key, len(fallback or [])))
    except (TypeError, ValueError):
        return 0


class KgVerifyBackend:
    """Default backend: wraps ``verify_hypothesis``. Always available."""

    name = "kg_verify"

    def __init__(self, *, verify_fn: Any = None) -> None:
        # ``verify_fn`` is injectable so tests never touch Neo4j.
        self._verify_fn = verify_fn

    def available(self) -> bool:  # noqa: D102 - protocol
        return True

    def _resolve_fn(self) -> Any:
        if self._verify_fn is not None:
            return self._verify_fn
        # Lazy: keep the autoresearch package import-light and service-tier-free.
        from brain_researcher.services.br_kg.query_service import verify_hypothesis

        return verify_hypothesis

    def verify(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict:
        fn = self._resolve_fn()
        entity_hints = [h for h in (scope.population, scope.modality) if h] or None
        call_args: dict[str, Any] = {
            "hypothesis": claim_text,
            "strictness": profile.strictness,
            "min_evidence_score": profile.min_evidence_score,
            "entity_hints": entity_hints,
        }
        result = fn(
            claim_text,
            strictness=profile.strictness,
            min_evidence_score=profile.min_evidence_score,
            entity_hints=entity_hints,
        )
        if not isinstance(result, dict):
            raise EvidenceBackendUnavailable(
                f"verify_hypothesis returned {type(result).__name__}, expected dict"
            )
        verdict_raw = str(result.get("verdict", "insufficient_evidence"))
        summary = result.get("summary") or {}
        supporting = result.get("supporting_evidence") or []
        conflicting = result.get("conflicting_evidence") or []
        return EvidenceVerdict(
            status=classify_kg_verdict(verdict_raw),
            backend=self.name,
            profile=profile.name,
            association_probability=result.get("confidence"),
            confidence=result.get("confidence"),
            normalized_claim=result.get("normalized_claim"),
            n_supporting=_summary_int(summary, "n_supporting", supporting),
            n_conflicting=_summary_int(summary, "n_conflicting", conflicting),
            supporting_refs=_refs(supporting),
            conflicting_refs=_refs(conflicting),
            reproducible_query={
                "backend": self.name,
                "fn": "verify_hypothesis",
                "profile": profile.name,
                "args": call_args,
            },
            raw={
                "verdict_raw": verdict_raw,
                "strictness": profile.strictness,
                "grounding_used_fallback": result.get("grounding_used_fallback"),
                "evidence_mode": result.get("evidence_mode"),
            },
            warnings=list(result.get("warnings") or []),
        )


#: Default interpreter for the isolated NeuroLang venv (Python >= 3.12, separate
#: pandas/nibabel/nilearn line). Overridable via ``BR_NEUROLANG_PYTHON``. NeuroLang
#: CANNOT be installed into the main 3.11 env (it pins pandas<2 / nibabel<5), so it
#: always runs out-of-process; see ``external/neurolang`` (git submodule).
_DEFAULT_NEUROLANG_PYTHON = "~/.venvs/neurolang-py312/bin/python"

#: Forward-inference *lift* (P(region|term) / P(region)) bar per strictness — the
#: ``reliable_study`` analog the sensitivity sweep swaps. A flat forward frequency
#: saturates, so the discriminative quantity is the lift over the base rate.
_LIFT_BY_STRICTNESS: dict[str, float] = {
    "high_recall": 1.5,
    "balanced": 2.0,
    "conservative": 3.0,
}
#: Minimal lift to count as evidence at all (below this, a higher bar would flip it).
_LENIENT_LIFT = 1.5
#: Below this many term-studies the lift is noise, not evidence.
_MIN_TERM_STUDIES = 3


def _status_from_lift(lift: float | None, bar: float) -> ClaimStatusV1:
    """Map a forward-inference lift onto the ladder (mirrors significance mapping).

    Lift over this profile's bar -> supported; over only the lenient bar (so it would
    flip under the sensitivity sweep) -> weakened; otherwise unresolved.
    """
    if lift is None:
        return ClaimStatusV1.unresolved
    if lift >= bar:
        return ClaimStatusV1.supported_within_scope
    if lift >= _LENIENT_LIFT:
        return ClaimStatusV1.weakened
    return ClaimStatusV1.unresolved


class NeuroLangBackend:
    """NeuroLang probabilistic-Datalog meta-analysis backend (out-of-process).

    Computes the Neurosynth-style forward inference ``P(activation@region | term)`` and
    its base-rate *lift* through NeuroLang's probabilistic-Datalog (PDL) solver over a
    coordinate corpus. NeuroLang pins ``python>=3.12`` and an incompatible
    ``pandas``/``nibabel``/``nilearn`` line, so it CANNOT live in the main 3.11 env: this
    backend prepares the facts here (it has nimare + grounding) and ships them as JSON to
    a standalone worker (:mod:`neurolang_worker`) run by the dedicated NeuroLang venv
    (``BR_NEUROLANG_PYTHON``). When the corpus or the venv is absent it declares itself
    unavailable and :func:`resolve_backend` transparently falls back to the KG backend.

    v0.1 runs a single forward-inference query; the value over NiMARE's ALE is that the
    PDL construction extends to compositional / multi-hop logical queries (future work).
    """

    name = "neurolang"
    # Cache of {python_path: bool} so ``available()`` probes the venv at most once.
    _import_ok: dict[str, bool] = {}

    def __init__(
        self,
        *,
        corpus: Any = None,
        venv_python: str | None = None,
        radius_mm: float = 10.0,
        label_threshold: float = 0.001,
        timeout_s: float = 120.0,
        run_worker: Any = None,
    ) -> None:
        self._corpus = corpus
        self._venv_python = os.path.expanduser(
            venv_python
            or os.environ.get("BR_NEUROLANG_PYTHON")
            or _DEFAULT_NEUROLANG_PYTHON
        )
        self._radius = float(radius_mm)
        self._label_threshold = float(label_threshold)
        self._timeout = float(timeout_s)
        # Injectable for hermetic tests (skip the real subprocess).
        self._run_worker = run_worker

    def _worker_path(self) -> str:
        from pathlib import Path

        return str(Path(__file__).with_name("neurolang_worker.py"))

    def _venv_imports_neurolang(self) -> bool:
        if self._run_worker is not None:
            return True
        py = self._venv_python
        if py in self._import_ok:
            return self._import_ok[py]
        ok = False
        if os.path.exists(py):
            import subprocess

            try:
                ok = (
                    subprocess.run(
                        [py, "-c", "import neurolang"],
                        capture_output=True,
                        timeout=60,
                    ).returncode
                    == 0
                )
            except (OSError, subprocess.SubprocessError):
                ok = False
        self._import_ok[py] = ok
        return ok

    def available(self) -> bool:  # noqa: D102 - protocol
        import importlib.util

        if self._corpus is None:
            return False
        if importlib.util.find_spec("nimare") is None:
            return False
        return self._venv_imports_neurolang()

    def _call_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._run_worker is not None:
            return self._run_worker(payload)
        import subprocess

        try:
            proc = subprocess.run(
                [self._venv_python, self._worker_path()],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise EvidenceBackendUnavailable(
                f"neurolang worker failed to run: {exc}"
            ) from exc
        if proc.returncode != 0:
            raise EvidenceBackendUnavailable(
                f"neurolang worker exited {proc.returncode}: {proc.stderr[:300]}"
            )
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise EvidenceBackendUnavailable(
                f"neurolang worker emitted non-JSON: {proc.stdout[:300]}"
            ) from exc
        if not out.get("ok", False):
            raise EvidenceBackendUnavailable(
                f"neurolang worker error: {out.get('error')}"
            )
        return out

    def _region_studies(self, xyz: tuple[float, float, float]) -> list[str]:
        """Study ids with at least one reported peak within ``radius`` of ``xyz``."""
        import numpy as np

        coords = getattr(self._corpus, "coordinates", None)
        if coords is None or not len(coords):
            return []
        # Use the analysis ``id`` (study+contrast, e.g. "10022492-1") so the id-space
        # matches ``corpus.ids`` / ``get_studies_by_label``; fall back to ``study_id``.
        id_col = "id" if "id" in coords.columns else "study_id"
        xyz_arr = np.asarray(xyz, dtype=float)
        dist = np.linalg.norm(
            coords[["x", "y", "z"]].to_numpy(dtype=float) - xyz_arr, axis=1
        )
        return sorted({str(s) for s in coords.loc[dist <= self._radius, id_col]})

    def verify(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict:
        if not self.available():
            raise EvidenceBackendUnavailable(
                "NeuroLangBackend needs a corpus, nimare, and the NeuroLang venv "
                f"({self._venv_python}); set BR_NEUROLANG_PYTHON"
            )
        region = resolve_region(claim_text)
        # Mask the resolved region's own surface words so the longest-match rule can't
        # return them as the cognitive term (e.g. "hippocampus" out-resolving "reward").
        excl = region_surface_aliases(region.region_label) if region is not None else ()
        term_res = resolve_term(claim_text, self._term_labels(), exclude_surfaces=excl)
        n_total = len(getattr(self._corpus, "ids", []))
        if region is None or term_res is None:
            missing = "region" if region is None else "term"
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                n_supporting=n_total,
                reproducible_query={
                    "backend": self.name,
                    "note": f"no {missing} resolved",
                },
                warnings=[
                    f"no target {missing} resolved from the claim (grounding lexicon)"
                ],
            )

        term_studies = [
            str(s)
            for s in self._corpus.get_studies_by_label(
                term_res.label, label_threshold=self._label_threshold
            )
        ]
        region_studies = self._region_studies(region.xyz)
        all_studies = [str(s) for s in getattr(self._corpus, "ids", [])]
        payload = {
            "query": "forward_inference",
            "term_studies": term_studies,
            "region_studies": region_studies,
            "all_studies": all_studies,
        }
        out = self._call_worker(payload)

        lift = out.get("lift")
        p_rgt = out.get("p_region_given_term")
        bar = _LIFT_BY_STRICTNESS.get(profile.strictness, 1.5)
        warnings = [
            "forward inference P(activation@region | term) via NeuroLang probabilistic "
            f"Datalog (out-of-process); region grounded to {region.region_label} "
            f"(conf {region.confidence}), term '{term_res.term}'"
        ]
        n_term = int(out.get("n_term", len(term_studies)))
        if n_term < _MIN_TERM_STUDIES:
            status = ClaimStatusV1.unresolved
            warnings.append(
                f"underpowered: only {n_term} studies about the term (<{_MIN_TERM_STUDIES})"
            )
        else:
            status = _status_from_lift(lift, bar)
        assoc = max(0.0, min(1.0, p_rgt)) if isinstance(p_rgt, int | float) else None
        return EvidenceVerdict(
            status=status,
            backend=self.name,
            profile=profile.name,
            association_probability=assoc,
            confidence=assoc,
            inference="forward_inference",
            region_confidence=region.confidence,
            term_confidence=term_res.confidence,
            region_source=region.source,
            term_source=term_res.source,
            n_supporting=n_term,
            reproducible_query={
                "backend": self.name,
                "engine": "neurolang.frontend.NeurolangPDL",
                "query": "forward_inference",
                "term": term_res.label,
                "target_region": region.name,
                "target_region_label": region.region_label,
                "target_xyz": list(region.xyz),
                "radius_mm": self._radius,
                "label_threshold": self._label_threshold,
                "lift_bar": bar,
                "strictness": profile.strictness,
                "venv_python": self._venv_python,
            },
            raw={
                "p_region_given_term": p_rgt,
                "p_region": out.get("p_region"),
                "lift": lift,
                "lift_bar": bar,
                "n_term": n_term,
                "n_region": out.get("n_region"),
                "n_total": n_total,
                "inference": "forward_inference",
                "neurolang_version": out.get("neurolang_version"),
            },
            warnings=warnings,
        )

    def verify_specificity(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        exclude_terms: list[str],
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict:
        """Is the region–term association *specific*, or driven by a rival term?

        Compositional query NiMARE cannot express: ``P(region | term AND NOT {confounds})``
        via a NeuroLang Datalog negation rule, compared against ``P(region | term)``. The
        ``exclude_terms`` are the claim's rival explanations (e.g. ``allowed_alternatives``
        / a hypothesis's ``alternative_explanations``). The status reflects the *specific*
        lift; a large drop when the confounds are removed is surfaced as a warning.
        """
        if not self.available():
            raise EvidenceBackendUnavailable(
                "NeuroLangBackend needs a corpus, nimare, and the NeuroLang venv "
                f"({self._venv_python}); set BR_NEUROLANG_PYTHON"
            )
        region = resolve_region(claim_text)
        labels = self._term_labels()
        # Same region-word mask as verify(): keep the region's own surface from hijacking
        # the term slot when resolving the term for the specificity contrast.
        excl = region_surface_aliases(region.region_label) if region is not None else ()
        term_res = resolve_term(claim_text, labels, exclude_surfaces=excl)
        n_total = len(getattr(self._corpus, "ids", []))
        if region is None or term_res is None:
            missing = "region" if region is None else "term"
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                n_supporting=n_total,
                reproducible_query={
                    "backend": self.name,
                    "note": f"no {missing} resolved",
                },
                warnings=[
                    f"no target {missing} resolved from the claim (grounding lexicon)"
                ],
            )

        include_studies = [
            str(s)
            for s in self._corpus.get_studies_by_label(
                term_res.label, label_threshold=self._label_threshold
            )
        ]
        # Resolve each rival term to a corpus label and pull its studies (skip unmatched).
        exclude_studies: dict[str, list[str]] = {}
        unresolved_excludes: list[str] = []
        for raw_term in exclude_terms:
            res = resolve_term(raw_term, labels)
            if res is None:
                unresolved_excludes.append(raw_term)
                continue
            exclude_studies[res.term] = [
                str(s)
                for s in self._corpus.get_studies_by_label(
                    res.label, label_threshold=self._label_threshold
                )
            ]

        out = self._call_worker(
            {
                "query": "compositional_forward",
                "include_studies": include_studies,
                "exclude_studies": exclude_studies,
                "region_studies": self._region_studies(region.xyz),
                "all_studies": [str(s) for s in getattr(self._corpus, "ids", [])],
            }
        )

        bar = _LIFT_BY_STRICTNESS.get(profile.strictness, 1.5)
        lift_specific = out.get("lift_specific")
        lift_include = out.get("lift_include")
        p_specific = out.get("p_region_given_specific")
        drop = out.get("specificity_drop")
        n_eligible = int(out.get("n_eligible", 0))
        warnings = [
            "compositional specificity: P(region | term AND NOT rivals) via NeuroLang "
            f"Datalog negation; region {region.region_label} (conf {region.confidence}), "
            f"term '{term_res.term}', excluded {sorted(exclude_studies)}"
        ]
        if unresolved_excludes:
            warnings.append(
                f"rival terms not in the corpus vocab (ignored): {unresolved_excludes}"
            )
        if n_eligible < _MIN_TERM_STUDIES:
            status = ClaimStatusV1.unresolved
            warnings.append(
                f"underpowered: only {n_eligible} studies survive the exclusion (<{_MIN_TERM_STUDIES})"
            )
        else:
            status = _status_from_lift(lift_specific, bar)
        # The association cleared the bar pooled but not after removing the rival(s):
        # it is not specific to the claimed construct.
        if (
            lift_include is not None
            and lift_specific is not None
            and lift_include >= bar
            and lift_specific < bar
        ):
            warnings.append(
                f"NOT specific: association clears the bar pooled (lift {lift_include:.2f}) but "
                f"collapses after excluding rivals (lift {lift_specific:.2f}) — likely confounded"
            )
        assoc = (
            max(0.0, min(1.0, p_specific))
            if isinstance(p_specific, int | float)
            else None
        )
        return EvidenceVerdict(
            status=status,
            backend=self.name,
            profile=profile.name,
            association_probability=assoc,
            confidence=assoc,
            inference="forward_inference",
            region_confidence=region.confidence,
            term_confidence=term_res.confidence,
            region_source=region.source,
            term_source=term_res.source,
            n_supporting=n_eligible,
            reproducible_query={
                "backend": self.name,
                "engine": "neurolang.frontend.NeurolangPDL",
                "query": "compositional_forward",
                "term": term_res.label,
                "exclude_terms": sorted(exclude_studies),
                "target_region": region.name,
                "target_region_label": region.region_label,
                "target_xyz": list(region.xyz),
                "radius_mm": self._radius,
                "lift_bar": bar,
                "strictness": profile.strictness,
                "venv_python": self._venv_python,
            },
            raw={
                "p_region_given_specific": p_specific,
                "p_region_given_include": out.get("p_region_given_include"),
                "p_region": out.get("p_region"),
                "lift_specific": lift_specific,
                "lift_include": lift_include,
                "specificity_drop": drop,
                "lift_bar": bar,
                "n_include": out.get("n_include"),
                "n_eligible": n_eligible,
                "n_excluded": out.get("n_excluded"),
                "n_total": n_total,
                "inference": "forward_inference",
                "neurolang_version": out.get("neurolang_version"),
            },
            warnings=warnings,
        )

    def verify_network(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        regions: list[str],
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict:
        """Do ``regions`` *co-activate* for the claim's term — beyond independence?

        Multi-region / network query NiMARE cannot express: a NeuroLang Datalog
        conjunction ``CoActive(s) :- Reg0(s), Reg1(s), ...`` carves studies that peak in
        ALL regions, and the **co-activation lift** ``P(joint|term) / Π P(region_i|term)``
        separates an integrated network (>1) from parallel/independent recruitment (~1).
        The status reflects the joint forward lift; co-activation ~<1 downgrades a
        supported joint to ``weakened`` (associated but not integrated).
        """
        if not self.available():
            raise EvidenceBackendUnavailable(
                "NeuroLangBackend needs a corpus, nimare, and the NeuroLang venv "
                f"({self._venv_python}); set BR_NEUROLANG_PYTHON"
            )
        # Mask the caller-supplied region names so they can't hijack the term slot.
        term_res = resolve_term(
            claim_text, self._term_labels(), exclude_surfaces=tuple(regions)
        )
        n_total = len(getattr(self._corpus, "ids", []))
        resolved: dict[str, list[str]] = {}
        unresolved_regions: list[str] = []
        for name in regions:
            reg = resolve_region(name)
            if reg is None:
                unresolved_regions.append(name)
                continue
            resolved[reg.region_label] = self._region_studies(reg.xyz)
        if term_res is None or len(resolved) < 2:
            why = "term" if term_res is None else "two resolvable regions"
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                n_supporting=n_total,
                reproducible_query={"backend": self.name, "note": f"need a {why}"},
                warnings=[
                    f"network query needs a {why}; "
                    f"resolved regions {sorted(resolved)}, unresolved {unresolved_regions}"
                ],
            )

        term_studies = [
            str(s)
            for s in self._corpus.get_studies_by_label(
                term_res.label, label_threshold=self._label_threshold
            )
        ]
        out = self._call_worker(
            {
                "query": "network_coactivation",
                "term_studies": term_studies,
                "region_studies": resolved,
                "all_studies": [str(s) for s in getattr(self._corpus, "ids", [])],
            }
        )

        bar = _LIFT_BY_STRICTNESS.get(profile.strictness, 1.5)
        joint_lift = out.get("joint_forward_lift")
        coact = out.get("coactivation_lift")
        p_joint = out.get("p_joint_given_term")
        n_joint = int(out.get("n_joint", 0))
        warnings = [
            "network co-activation: P(all regions peak | term) via NeuroLang multi-region "
            f"Datalog conjunction; term '{term_res.term}', regions {sorted(resolved)}"
        ]
        if unresolved_regions:
            warnings.append(
                f"regions not in the grounding lexicon (ignored): {unresolved_regions}"
            )
        if n_joint < _MIN_TERM_STUDIES:
            status = ClaimStatusV1.unresolved
            warnings.append(
                f"underpowered: only {n_joint} studies co-activate all regions (<{_MIN_TERM_STUDIES})"
            )
        else:
            status = _status_from_lift(joint_lift, bar)
        # Associated with the term, but not co-activating beyond chance: parallel
        # recruitment, not an integrated network — too weak to call a network claim.
        if (
            coact is not None
            and coact < 1.0
            and status is ClaimStatusV1.supported_within_scope
        ):
            status = ClaimStatusV1.weakened
            warnings.append(
                f"regions associate with the term but do NOT co-activate beyond independence "
                f"(co-activation lift {coact:.2f}) — parallel recruitment, not integration"
            )
        assoc = (
            max(0.0, min(1.0, p_joint)) if isinstance(p_joint, int | float) else None
        )
        return EvidenceVerdict(
            status=status,
            backend=self.name,
            profile=profile.name,
            association_probability=assoc,
            confidence=assoc,
            inference="forward_inference",
            term_confidence=term_res.confidence,
            term_source=term_res.source,
            n_supporting=n_joint,
            reproducible_query={
                "backend": self.name,
                "engine": "neurolang.frontend.NeurolangPDL",
                "query": "network_coactivation",
                "term": term_res.label,
                "regions": sorted(resolved),
                "radius_mm": self._radius,
                "lift_bar": bar,
                "strictness": profile.strictness,
                "venv_python": self._venv_python,
            },
            raw={
                "p_joint_given_term": p_joint,
                "p_joint": out.get("p_joint"),
                "joint_forward_lift": joint_lift,
                "coactivation_lift": coact,
                "per_region_given_term": out.get("per_region_given_term"),
                "expected_if_independent": out.get("expected_if_independent"),
                "lift_bar": bar,
                "n_joint": n_joint,
                "n_term": out.get("n_term"),
                "n_total": n_total,
                "inference": "forward_inference",
                "neurolang_version": out.get("neurolang_version"),
            },
            warnings=warnings,
        )

    def _term_labels(self) -> list[str]:
        ann = getattr(self._corpus, "annotations", None)
        if ann is None:
            return []
        meta = {"id", "study_id", "contrast_id"}
        return [c for c in ann.columns if c not in meta]


# Evidence-profile strictness -> significance bar (the ``reliable_study`` analog the
# sensitivity sweep swaps): lenient recall vs conservative.
_ALPHA_BY_STRICTNESS: dict[str, float] = {
    "high_recall": 0.05,
    "balanced": 0.01,
    "conservative": 0.001,
}

#: A finding significant only at the lenient bar (not this profile's) is "weakened".
_LENIENT_ALPHA = 0.05


def _status_from_significance(
    z_positive: bool, p: float, alpha: float
) -> ClaimStatusV1:
    """Map a one-sided significance onto the ladder.

    Significant at this profile's bar -> supported; significant only at the lenient
    bar (so it would flip under the sensitivity sweep) -> weakened; otherwise
    unresolved. ``z_positive`` is always True for forward convergence and ``z>0`` for
    reverse over-representation (a negative reverse z never supports the claim).
    """
    if z_positive and p <= alpha:
        return ClaimStatusV1.supported_within_scope
    if z_positive and p <= _LENIENT_ALPHA:
        return ClaimStatusV1.weakened
    return ClaimStatusV1.unresolved


class NimareBackend:
    """Real coordinate-based meta-analysis backend over a curated corpus (NiMARE).

    Runs an ALE convergence test over the corpus once (cached) and queries the
    statistic at the claim's target MNI coordinate (resolved via the built-in region
    lexicon). This is FORWARD-convergence evidence — P(convergent activation | corpus),
    NOT reverse inference — and is reported as such (a warning). The evidence-profile
    strictness maps to the significance bar (``high_recall`` a=0.05 / ``balanced`` a=0.01
    / ``conservative`` a=0.001): the ``reliable_study`` analog the sensitivity sweep
    swaps, so the same evidence can be supported at a lenient bar and unresolved at a
    strict one. NiMARE/nilearn are imported lazily.

    REVERSE INFERENCE: when the corpus carries term annotations and the claim resolves
    to one (and ``inference_mode != "forward"``), the backend instead computes
    Neurosynth-style P(term | region) via ``MKDAChi2`` (``inference="reverse_specificity"``)
    — the real answer to a cognitive-engagement claim that forward convergence cannot
    give (so the compiler's forward-only guard does not cap it).
    """

    name = "nimare"

    def __init__(
        self,
        *,
        corpus: Any = None,
        radius_mm: float = 10.0,
        inference_mode: str = "auto",
        label_threshold: float = 0.001,
    ) -> None:
        self._corpus = corpus
        self._radius = float(radius_mm)
        # "auto": reverse (P(term|region)) when a corpus term matches the claim, else
        # forward ALE convergence. "forward"/"reverse" force one mode.
        self._mode = inference_mode
        # Term-present cutoff for the reverse split. 0.001 is the Neurosynth TF-IDF
        # convention and also cleanly separates the binary 1.0/0.0 synthetic labels.
        self._label_threshold = float(label_threshold)
        self._result = None  # cached ALE fit (claim-independent)
        self._reverse_cache: dict[str, Any] = {}  # term -> cached MKDAChi2 result

    def available(self) -> bool:  # noqa: D102 - protocol
        if self._corpus is None:
            return False
        import importlib.util

        return importlib.util.find_spec("nimare") is not None

    def _fit(self) -> Any:
        if self._result is None:
            from nimare.meta.cbma.ale import ALE

            self._result = ALE(null_method="approximate").fit(self._corpus)
        return self._result

    def _sample(self, result: Any, key: str, xyz: tuple[float, float, float]) -> float:
        import numpy as np
        from nilearn.maskers import NiftiSpheresMasker

        img = result.get_map(key, return_type="image")
        masker = NiftiSpheresMasker([xyz], radius=self._radius)
        return float(np.nan_to_num(masker.fit_transform(img)).mean())

    def _term_labels(self) -> list[str]:
        ann = getattr(self._corpus, "annotations", None)
        if ann is None:
            return []
        meta = {"id", "study_id", "contrast_id"}
        return [c for c in ann.columns if c not in meta]

    def _fit_reverse(self, term: str) -> Any:
        if term not in self._reverse_cache:
            from nimare.meta.cbma.mkda import MKDAChi2

            present = list(
                self._corpus.get_studies_by_label(
                    term, label_threshold=self._label_threshold
                )
            )
            absent = sorted(set(self._corpus.ids) - set(present))
            if not present or not absent:
                raise EvidenceBackendUnavailable(
                    f"reverse inference needs both term-present and term-absent studies for {term!r}"
                )
            self._reverse_cache[term] = MKDAChi2().fit(
                self._corpus.slice(present), self._corpus.slice(absent)
            )
        return self._reverse_cache[term]

    def _reverse_verdict(
        self,
        term_res: TermResolution,
        region: RegionResolution,
        profile: EvidenceProfile,
        n_studies: int,
    ) -> EvidenceVerdict:
        """Neurosynth-style reverse inference P(term | region) via MKDAChi2."""
        result = self._fit_reverse(term_res.label)
        xyz = region.xyz
        z = self._sample(result, "z_desc-association", xyz)
        p = self._sample(result, "p_desc-association", xyz)
        posterior = self._sample(
            result, "prob_desc-FgA", xyz
        )  # P(term | activation@region)
        alpha = _ALPHA_BY_STRICTNESS.get(profile.strictness, 0.05)
        # Over-representation only: a negative association z means the term is LESS
        # likely at this region, which never supports an engagement claim.
        status = _status_from_significance(z > 0, p, alpha)
        assoc = max(0.0, min(1.0, posterior))
        return EvidenceVerdict(
            status=status,
            backend=self.name,
            profile=profile.name,
            association_probability=assoc,
            confidence=assoc,
            inference="reverse_specificity",
            region_confidence=region.confidence,
            term_confidence=term_res.confidence,
            region_source=region.source,
            term_source=term_res.source,
            n_supporting=n_studies,
            reproducible_query={
                "backend": self.name,
                "estimator": "MKDAChi2",
                "inference": "reverse",
                "term": term_res.label,
                "target_region": region.name,
                "target_region_label": region.region_label,
                "target_xyz": list(xyz),
                "radius_mm": self._radius,
                "alpha": alpha,
                "strictness": profile.strictness,
            },
            raw={
                "z_association": z,
                "p_association": p,
                "p_term_given_region": posterior,
                "alpha": alpha,
                "inference": "reverse_specificity",
                "term": term_res.term,
                "region_confidence": region.confidence,
                "term_confidence": term_res.confidence,
                "n_studies": n_studies,
            },
            warnings=[
                "reverse inference P(term|region) via MKDAChi2 (Neurosynth-style); "
                f"term '{term_res.term}' vs rest of corpus; region grounded to "
                f"{region.region_label} (conf {region.confidence})"
            ],
        )

    def _region_studies(self, xyz: tuple[float, float, float]) -> list[str]:
        """Study ids with at least one reported peak within ``radius_mm`` of ``xyz``.

        In-process coordinate membership over ``corpus.coordinates`` — the set primitive
        the compositional specificity/network queries need, computed without NiMARE's
        CBMA estimators (which cannot express them).
        """
        import numpy as np

        coords = self._corpus.coordinates
        dx = coords["x"].to_numpy(dtype=float) - float(xyz[0])
        dy = coords["y"].to_numpy(dtype=float) - float(xyz[1])
        dz = coords["z"].to_numpy(dtype=float) - float(xyz[2])
        within = (dx * dx + dy * dy + dz * dz) <= (self._radius * self._radius)
        return sorted({str(s) for s in np.asarray(coords["id"])[within]})

    def verify_specificity(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        exclude_terms: list[str],
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict:
        """Is the region-term association *specific*, or driven by a rival term?

        Set-based analogue of the NeuroLang ``P(region | term AND NOT rivals)`` contrast
        that NiMARE's estimators cannot express: compares the fraction of *term* studies
        peaking at the target region against the same fraction with every ``exclude_terms``
        (rival) study removed, reported as a lift over the corpus base rate. A large drop
        when the rivals are excluded is surfaced as a warning. This is coordinate set
        arithmetic over the corpus, not a NiMARE CBMA.
        """
        if not self.available():
            raise EvidenceBackendUnavailable(
                "NimareBackend needs a corpus and nimare installed"
            )
        region = resolve_region(claim_text)
        labels = self._term_labels()
        excl = region_surface_aliases(region.region_label) if region is not None else ()
        term_res = resolve_term(claim_text, labels, exclude_surfaces=excl)
        all_ids = {str(s) for s in getattr(self._corpus, "ids", [])}
        n_total = len(all_ids)
        if region is None or term_res is None:
            missing = "region" if region is None else "term"
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                n_supporting=n_total,
                reproducible_query={
                    "backend": self.name,
                    "note": f"no {missing} resolved",
                },
                warnings=[
                    f"no target {missing} resolved from the claim (grounding lexicon)"
                ],
            )
        region_ids = set(self._region_studies(region.xyz))
        include = {
            str(s)
            for s in self._corpus.get_studies_by_label(
                term_res.label, label_threshold=self._label_threshold
            )
        }
        exclude_ids: set[str] = set()
        resolved_rivals: dict[str, int] = {}
        unresolved_excludes: list[str] = []
        for raw_term in exclude_terms:
            res = resolve_term(raw_term, labels)
            if res is None:
                unresolved_excludes.append(raw_term)
                continue
            rs = {
                str(s)
                for s in self._corpus.get_studies_by_label(
                    res.label, label_threshold=self._label_threshold
                )
            }
            resolved_rivals[res.term] = len(rs)
            exclude_ids |= rs
        specific = include - exclude_ids
        base_rate = (len(region_ids) / n_total) if n_total else 0.0

        def _frac(subset: set[str]) -> float:
            return (len(region_ids & subset) / len(subset)) if subset else 0.0

        p_term = _frac(include)
        p_specific = _frac(specific)
        specific_lift = (p_specific / base_rate) if base_rate > 0 else None
        retained = (p_specific / p_term) if p_term > 0 else 0.0
        bar = _LIFT_BY_STRICTNESS.get(profile.strictness, 1.5)
        if len(specific) < _MIN_TERM_STUDIES:
            status = ClaimStatusV1.unresolved
        else:
            status = _status_from_lift(specific_lift, bar)
        warnings = [
            "specificity: P(region peak | term AND NOT rivals) over corpus base rate via "
            f"coordinate set arithmetic (not a NiMARE CBMA); term '{term_res.term}', "
            f"rivals {sorted(resolved_rivals)}; region grounded to {region.region_label}"
        ]
        if unresolved_excludes:
            warnings.append(
                f"rival terms not in the corpus lexicon (ignored): {unresolved_excludes}"
            )
        if p_term > 0 and retained < 0.5:
            warnings.append(
                f"association drops to {retained:.0%} of its value when rivals are excluded "
                "— partly confound-driven, not fully specific"
            )
        assoc = max(0.0, min(1.0, p_specific))
        return EvidenceVerdict(
            status=status,
            backend=self.name,
            profile=profile.name,
            association_probability=assoc,
            confidence=assoc,
            inference="specificity_set_contrast",
            region_confidence=region.confidence,
            term_confidence=term_res.confidence,
            region_source=region.source,
            term_source=term_res.source,
            n_supporting=len(specific),
            n_conflicting=len(exclude_ids),
            reproducible_query={
                "backend": self.name,
                "method": "coordinate_set_contrast",
                "term": term_res.label,
                "exclude_terms": sorted(resolved_rivals),
                "target_region": region.name,
                "target_region_label": region.region_label,
                "target_xyz": list(region.xyz),
                "radius_mm": self._radius,
                "lift_bar": bar,
                "strictness": profile.strictness,
            },
            raw={
                "p_region_given_term": p_term,
                "p_region_given_term_not_rivals": p_specific,
                "base_rate": base_rate,
                "specific_lift": specific_lift,
                "retained_fraction": retained,
                "n_term": len(include),
                "n_excluded": len(exclude_ids),
                "n_specific": len(specific),
                "n_total": n_total,
                "lift_bar": bar,
                "inference": "specificity_set_contrast",
            },
            warnings=warnings,
        )

    def verify_network(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        regions: list[str],
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict:
        """Do ``regions`` *co-activate* for the claim's term, beyond independence?

        Set-based analogue of the NeuroLang multi-region conjunction NiMARE cannot
        express: studies peaking in ALL ``regions`` (coordinate membership) intersected
        with the term studies give ``P(joint | term)``; the co-activation lift
        ``P(joint|term) / prod_i P(region_i|term)`` separates an integrated network (>1)
        from parallel recruitment (~1). Status is the joint forward lift; a co-activation
        lift below 1 downgrades a supported joint to ``weakened``.
        """
        if not self.available():
            raise EvidenceBackendUnavailable(
                "NimareBackend needs a corpus and nimare installed"
            )
        term_res = resolve_term(
            claim_text, self._term_labels(), exclude_surfaces=tuple(regions)
        )
        all_ids = {str(s) for s in getattr(self._corpus, "ids", [])}
        n_total = len(all_ids)
        resolved: dict[str, set[str]] = {}
        unresolved_regions: list[str] = []
        for name in regions:
            reg = resolve_region(name)
            if reg is None:
                unresolved_regions.append(name)
                continue
            resolved[reg.region_label] = set(self._region_studies(reg.xyz))
        if term_res is None or len(resolved) < 2:
            why = "term" if term_res is None else "two resolvable regions"
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                n_supporting=n_total,
                reproducible_query={"backend": self.name, "note": f"need a {why}"},
                warnings=[
                    f"network query needs a {why}; resolved regions {sorted(resolved)}, "
                    f"unresolved {unresolved_regions}"
                ],
            )
        term_ids = {
            str(s)
            for s in self._corpus.get_studies_by_label(
                term_res.label, label_threshold=self._label_threshold
            )
        }
        if not term_ids:
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                n_supporting=0,
                reproducible_query={
                    "backend": self.name,
                    "note": "no studies for the term",
                },
                warnings=[f"no corpus studies carry the term '{term_res.term}'"],
            )
        joint = set.intersection(*resolved.values())
        per_region_given_term = {
            lbl: (len(term_ids & rs) / len(term_ids)) for lbl, rs in resolved.items()
        }
        n_joint = len(term_ids & joint)
        p_joint_given_term = n_joint / len(term_ids)
        expected_if_independent = 1.0
        for v in per_region_given_term.values():
            expected_if_independent *= v
        coact = (
            (p_joint_given_term / expected_if_independent)
            if expected_if_independent > 0
            else None
        )
        p_joint_corpus = (len(joint) / n_total) if n_total else 0.0
        joint_lift = (
            (p_joint_given_term / p_joint_corpus) if p_joint_corpus > 0 else None
        )
        bar = _LIFT_BY_STRICTNESS.get(profile.strictness, 1.5)
        warnings = [
            "network co-activation: P(all regions peak | term) via coordinate set "
            f"intersection (not a NiMARE CBMA); term '{term_res.term}', regions {sorted(resolved)}"
        ]
        if unresolved_regions:
            warnings.append(
                f"regions not in the grounding lexicon (ignored): {unresolved_regions}"
            )
        if n_joint < _MIN_TERM_STUDIES:
            status = ClaimStatusV1.unresolved
            warnings.append(
                f"underpowered: only {n_joint} studies co-activate all regions (<{_MIN_TERM_STUDIES})"
            )
        else:
            status = _status_from_lift(joint_lift, bar)
        if (
            coact is not None
            and coact < 1.0
            and status is ClaimStatusV1.supported_within_scope
        ):
            status = ClaimStatusV1.weakened
            warnings.append(
                f"regions associate with the term but do NOT co-activate beyond independence "
                f"(co-activation lift {coact:.2f}) — parallel recruitment, not integration"
            )
        assoc = max(0.0, min(1.0, p_joint_given_term))
        return EvidenceVerdict(
            status=status,
            backend=self.name,
            profile=profile.name,
            association_probability=assoc,
            confidence=assoc,
            inference="network_set_conjunction",
            term_confidence=term_res.confidence,
            term_source=term_res.source,
            n_supporting=n_joint,
            reproducible_query={
                "backend": self.name,
                "method": "coordinate_set_conjunction",
                "term": term_res.label,
                "regions": sorted(resolved),
                "radius_mm": self._radius,
                "lift_bar": bar,
                "strictness": profile.strictness,
            },
            raw={
                "p_joint_given_term": p_joint_given_term,
                "p_joint": p_joint_corpus,
                "joint_forward_lift": joint_lift,
                "coactivation_lift": coact,
                "per_region_given_term": per_region_given_term,
                "expected_if_independent": expected_if_independent,
                "lift_bar": bar,
                "n_joint": n_joint,
                "n_term": len(term_ids),
                "n_total": n_total,
                "inference": "network_set_conjunction",
            },
            warnings=warnings,
        )

    def verify(
        self,
        claim_text: str,
        scope: ScopeBoundaryV1,
        *,
        profile: EvidenceProfile = DEFAULT_PROFILE,
    ) -> EvidenceVerdict:
        if not self.available():
            raise EvidenceBackendUnavailable(
                "NimareBackend needs a corpus and nimare installed"
            )
        region = resolve_region(claim_text)
        n_studies = len(getattr(self._corpus, "ids", []))
        if region is None:
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                n_supporting=n_studies,
                reproducible_query={
                    "backend": self.name,
                    "note": "no target region resolved",
                },
                warnings=[
                    "no target region resolved from the claim (grounding lexicon)"
                ],
            )

        # Reverse inference (P(term | region), MKDAChi2) when the corpus carries a
        # matching term annotation — the real answer to a cognitive-engagement claim,
        # which forward convergence cannot give.
        term_res = (
            resolve_term(
                claim_text,
                self._term_labels(),
                exclude_surfaces=region_surface_aliases(region.region_label),
            )
            if self._mode in ("auto", "reverse")
            else None
        )
        if term_res is not None:
            return self._reverse_verdict(term_res, region, profile, n_studies)
        if self._mode == "reverse":
            return EvidenceVerdict(
                status=ClaimStatusV1.unresolved,
                backend=self.name,
                profile=profile.name,
                inference="reverse_specificity",
                region_confidence=region.confidence,
                region_source=region.source,
                n_supporting=n_studies,
                reproducible_query={
                    "backend": self.name,
                    "note": "no corpus term matched the claim",
                },
                warnings=[
                    "reverse inference requested but no corpus term matched the claim"
                ],
            )

        # Forward convergence (ALE) fallback.
        result = self._fit()
        xyz = region.xyz
        z = self._sample(result, "z", xyz)
        p = self._sample(result, "p", xyz)
        alpha = _ALPHA_BY_STRICTNESS.get(profile.strictness, 0.05)
        status = _status_from_significance(True, p, alpha)
        assoc = max(0.0, min(1.0, 1.0 - p))
        return EvidenceVerdict(
            status=status,
            backend=self.name,
            profile=profile.name,
            association_probability=assoc,
            confidence=assoc,
            inference="forward_convergence",
            region_confidence=region.confidence,
            region_source=region.source,
            n_supporting=n_studies,
            reproducible_query={
                "backend": self.name,
                "estimator": "ALE(null_method=approximate)",
                "target_region": region.name,
                "target_region_label": region.region_label,
                "target_xyz": list(xyz),
                "radius_mm": self._radius,
                "alpha": alpha,
                "strictness": profile.strictness,
            },
            raw={
                "z": z,
                "p": p,
                "alpha": alpha,
                "inference": "forward_convergence",
                "region_confidence": region.confidence,
                "n_studies": n_studies,
            },
            warnings=[
                "forward-convergence evidence (not reverse inference); region grounded "
                f"to {region.region_label} (conf {region.confidence})"
            ],
        )


#: Logical name -> constructor. Aliases collapse to the canonical backend.
_BACKENDS: dict[str, str] = {
    "kg_verify": "kg",
    "kg": "kg",
    "default": "kg",
    "neurolang": "neurolang",
    "nimare": "nimare",
    "neurosynth": "nimare",
}


def resolve_backend(
    name: str | None = None,
    *,
    fallback: ProbabilisticEvidenceBackend | None = None,
) -> ProbabilisticEvidenceBackend:
    """Resolve the configured backend, falling back when it is unavailable.

    Precedence: explicit ``name`` > ``BR_NEUROCLAIM_BACKEND`` env > ``kg_verify``.
    An unknown or unavailable backend logs and returns ``fallback`` (default
    :class:`KgVerifyBackend`), so the call site always gets a working backend.
    """
    fallback = fallback or KgVerifyBackend()
    requested = (
        (name or os.environ.get("BR_NEUROCLAIM_BACKEND") or "kg_verify").strip().lower()
    )
    canonical = _BACKENDS.get(requested)
    if canonical is None:
        logger.warning(
            "neuroclaim: unknown backend %r; using %s", requested, fallback.name
        )
        return fallback
    if canonical == "kg":
        return KgVerifyBackend()
    if canonical == "neurolang":
        corpus = None
        cache = os.environ.get("BR_NEUROCLAIM_CORPUS")
        if cache:
            try:
                from .corpus import load_neurosynth_corpus

                corpus = load_neurosynth_corpus(
                    cache, data_dir=os.environ.get("BR_NEUROCLAIM_SOURCE_DIR")
                )
            except Exception as exc:
                logger.warning("neuroclaim: corpus load failed (%s); falling back", exc)
        backend: ProbabilisticEvidenceBackend = NeuroLangBackend(corpus=corpus)
        if backend.available():
            return backend
        logger.warning(
            "neuroclaim: neurolang backend unavailable (corpus / venv %s); falling back to %s",
            os.environ.get("BR_NEUROLANG_PYTHON") or _DEFAULT_NEUROLANG_PYTHON,
            fallback.name,
        )
        return fallback
    if canonical == "nimare":
        corpus = None
        cache = os.environ.get("BR_NEUROCLAIM_CORPUS")
        if cache:
            try:
                from .corpus import load_neurosynth_corpus

                corpus = load_neurosynth_corpus(
                    cache, data_dir=os.environ.get("BR_NEUROCLAIM_SOURCE_DIR")
                )
            except Exception as exc:
                logger.warning("neuroclaim: corpus load failed (%s); falling back", exc)
        nimare_backend: ProbabilisticEvidenceBackend = NimareBackend(corpus=corpus)
        if nimare_backend.available():
            return nimare_backend
        logger.warning(
            "neuroclaim: nimare backend has no usable corpus (set BR_NEUROCLAIM_CORPUS); "
            "falling back to %s",
            fallback.name,
        )
        return fallback
    return fallback  # pragma: no cover - defensive
