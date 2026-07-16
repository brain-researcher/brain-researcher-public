#!/usr/bin/env python
"""Generate a V-HRL calibrated auditable ClaimCard from public Neurosynth evidence.

This script is intentionally narrow and rerunnable. It reads a local NiMARE
Neurosynth corpus, runs the evidence backend, and writes a JSON bundle plus a
Markdown summary under ``docs/results/`` by default.

The default backend is **NiMARE** (``pip install nimare nilearn`` -- standard
scientific-Python, no second interpreter). NeuroLang is an optional *reference*
engine (``--backend neurolang``) behind the committed reference card; it is not
required and must not be installed with ``pip install neurolang``. The public
checkout does not currently ship a verified NeuroLang bootstrap recipe; see
``reproducibility/auditable_claim_record/README.md`` for that boundary.

Inputs:
  --corpus: NiMARE Neurosynth dataset pickle. Defaults to BR_NEUROCLAIM_CORPUS or
    ``data/neurosynth_nimare/neurosynth_dataset_v7.pkl``.
  --source-dir: verified pinned raw bundle associated with ``--corpus``.
  --case: demo case to run. Defaults to ``working_memory``.
  --backend: ``nimare`` (default, light) or ``neurolang`` (optional reference).
  --output-dir: output directory. Defaults to the selected case's result folder.
  --venv-python: optional NeuroLang interpreter, only used with
    ``--backend neurolang``. Defaults to BR_NEUROLANG_PYTHON or
    ``~/.venvs/neurolang-py312/bin/python``.

Outputs:
  commitment_card.json (persisted before the first evidence query)
  evidence_verdicts.json
  claim_card.json
  demo_bundle.json
  README.md
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.society.calibration import (
    claim_structure_ceiling,
    compose_ceilings,
)
from brain_researcher.autoresearch.society.cards import (
    ClaimCardV1,
    ClaimSpecV1,
    ClaimStatusV1,
    CommitmentCardV1,
    EvidenceEngineRefV1,
    ScopeBoundaryV1,
    lock_commitment,
)
from brain_researcher.autoresearch.society.corpus import load_neurosynth_corpus
from brain_researcher.autoresearch.society.evidence_backend import (
    DEFAULT_PROFILE,
    STRICT_PROFILE,
    EvidenceVerdict,
    NeuroLangBackend,
    NimareBackend,
)
from brain_researcher.autoresearch.society.hypotheses import (
    CriticalTestV1,
    HypothesisSpecV1,
    reasoning_mode_ceiling,
)
from brain_researcher.autoresearch.society.multiverse import CeilingResult
from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_DATASET_PICKLE,
    DEFAULT_SOURCE_DIR,
    MANIFEST_FILENAME,
    converted_provenance_path,
    verify_converted_dataset,
)

DEFAULT_CORPUS = str(DEFAULT_DATASET_PICKLE)
DEFAULT_CASE_KEY = "working_memory"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUBRIC_ROOT = REPO_ROOT / "reproducibility" / "auditable_claim_record" / "rubrics"
RUBRIC_PATHS = {
    "strict_evidence_profile": RUBRIC_ROOT / "strict_evidence_profile.md",
    "compositional_specificity": RUBRIC_ROOT / "compositional_specificity.md",
    "network_coactivation": RUBRIC_ROOT / "network_coactivation.md",
}


@dataclass(frozen=True)
class DemoCase:
    key: str
    title: str
    output_dir: str
    claim_id: str
    claim_text: str
    hypothesis_id: str
    hypothesis_statement: str
    cause: str
    effect: str
    evidence_claim_text: str
    network_regions: tuple[str, ...]
    rival_terms: tuple[str, ...]
    predictions: tuple[str, ...]
    critical_test_measurements: tuple[str, ...]
    critical_test_comparison: str
    success_criteria: str
    failure_criteria: str
    specificity_display: str
    specificity_rationale: str
    network_display: str
    network_rationale: str
    calibrated_claim_text: str
    next_required_evidence: tuple[str, ...]


WORKING_MEMORY_CASE = DemoCase(
    key="working_memory",
    title="NeuroLang -> V-HRL Working-Memory Demo",
    output_dir="docs/results/neurolang_vhrl_working_memory_demo",
    claim_id="demo-wm-dlpfc-ips-v1",
    claim_text=(
        "Working-memory-labeled Neurosynth studies show dlPFC activation and "
        "dlPFC-IPS coactivation within coordinate evidence."
    ),
    hypothesis_id="hyp-wm-frontoparietal-v1",
    hypothesis_statement=(
        "Working-memory study labels are associated with frontoparietal coordinate "
        "evidence, including dlPFC activation and dlPFC-IPS coactivation."
    ),
    cause="working-memory term membership",
    effect="frontoparietal coordinate evidence",
    evidence_claim_text="the dlPFC is engaged during working memory",
    network_regions=("dlPFC", "IPS"),
    rival_terms=("attention",),
    predictions=(
        "dlPFC forward lift exceeds the default evidence bar for working memory.",
        "The dlPFC association survives excluding the rival term attention.",
        "dlPFC and IPS coactivate above their independent recruitment baseline.",
    ),
    critical_test_measurements=(
        "P(dlPFC | working memory)",
        "P(dlPFC | working memory AND NOT attention)",
        "P(dlPFC AND IPS | working memory) / independent expectation",
    ),
    critical_test_comparison=(
        "default vs conservative lift bar; pooled vs attention-excluded; "
        "joint dlPFC-IPS recruitment vs independence"
    ),
    success_criteria=(
        "Default NeuroLang forward evidence and dlPFC-IPS coactivation clear the "
        "lenient evidence bar."
    ),
    failure_criteria=(
        "Downgrade the claim if conservative evidence, attention-excluded "
        "specificity, or dlPFC-IPS coactivation does not clear its bar."
    ),
    specificity_display="specificity-not-attention",
    specificity_rationale="Compositional query: working memory AND NOT attention.",
    network_display="network-coactivation-dlpfc-ips",
    network_rationale="Multi-region NeuroLang conjunction for dlPFC and IPS.",
    calibrated_claim_text=(
        "Within Neurosynth coordinate evidence, working memory shows dlPFC forward "
        "association and dlPFC-IPS coactivation, but the claim is threshold-fragile "
        "under the conservative NeuroLang evidence profile; report it as weakened "
        "rather than clean support."
    ),
    next_required_evidence=(
        "Independent dataset replication before clean supported_within_scope wording.",
        "Do not use causal or necessity language from coordinate meta-analysis alone.",
        "Run a pipeline-level multiverse only when binding a dataset-specific contrast.",
    ),
)

RESPONSE_INHIBITION_BOUNDARY_CASE = DemoCase(
    key="response_inhibition_boundary",
    title="NeuroLang -> V-HRL Response-Inhibition Boundary Demo",
    output_dir="docs/results/neurolang_vhrl_response_inhibition_boundary_demo",
    claim_id="demo-response-inhibition-acc-ifg-v1",
    claim_text=(
        "Response-inhibition-labeled Neurosynth studies establish an ACC-IFG "
        "control-network pattern within coordinate evidence."
    ),
    hypothesis_id="hyp-response-inhibition-acc-ifg-v1",
    hypothesis_statement=(
        "Response-inhibition study labels are associated with ACC coordinate evidence, "
        "but ACC-IFG network integration must be checked separately."
    ),
    cause="response-inhibition term membership",
    effect="ACC and IFG coordinate evidence",
    evidence_claim_text="response inhibition engages ACC",
    network_regions=("ACC", "IFG"),
    rival_terms=("attention",),
    predictions=(
        "ACC forward lift exceeds the default evidence bar for response inhibition.",
        "The ACC association survives excluding the rival term attention.",
        "ACC and IFG coactivation clears the network evidence bar before a network claim is allowed.",
    ),
    critical_test_measurements=(
        "P(ACC | response inhibition)",
        "P(ACC | response inhibition AND NOT attention)",
        "P(ACC AND IFG | response inhibition) / independent expectation",
    ),
    critical_test_comparison=(
        "default vs conservative lift bar; pooled vs attention-excluded; "
        "joint ACC-IFG recruitment vs independence"
    ),
    success_criteria=(
        "Default ACC forward evidence, attention-excluded specificity, and ACC-IFG "
        "network coactivation all clear their evidence bars."
    ),
    failure_criteria=(
        "If ACC-IFG network coactivation does not clear its evidence bar, do not claim "
        "a response-inhibition control-network mechanism."
    ),
    specificity_display="specificity-not-attention",
    specificity_rationale="Compositional query: response inhibition AND NOT attention.",
    network_display="network-coactivation-acc-ifg",
    network_rationale="Multi-region NeuroLang conjunction for ACC and IFG.",
    calibrated_claim_text=(
        "Within Neurosynth coordinate evidence, response inhibition shows ACC forward "
        "association and survives attention-excluded specificity, but the ACC-IFG "
        "network axis does not clear its evidence bar; report ACC association only "
        "and treat the ACC-IFG network claim as unresolved."
    ),
    next_required_evidence=(
        "Do not claim ACC-IFG network integration until the network axis clears.",
        "Independent dataset replication before clean supported_within_scope wording.",
        "Do not use causal, necessity, or mechanism language from coordinate meta-analysis alone.",
    ),
)

CASES = {
    WORKING_MEMORY_CASE.key: WORKING_MEMORY_CASE,
    RESPONSE_INHIBITION_BOUNDARY_CASE.key: RESPONSE_INHIBITION_BOUNDARY_CASE,
}


@dataclass(frozen=True)
class DemoInputs:
    claim: ClaimSpecV1
    hypothesis: HypothesisSpecV1


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_path_ref(path: Path, *, repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Describe a path without persisting a machine- or clone-specific prefix."""
    resolved = path.expanduser().resolve()
    try:
        portable = resolved.relative_to(repo_root.expanduser().resolve()).as_posix()
        kind = "repo_relative"
    except ValueError:
        portable = resolved.name
        kind = "external_basename"
    return {"kind": kind, "path": portable}


def _rubric_refs(
    *,
    rubric_paths: dict[str, Path] = RUBRIC_PATHS,
    repo_root: Path = REPO_ROOT,
) -> dict[str, dict[str, str]]:
    """Build clone-stable references to the exact rubric content being sealed."""
    refs: dict[str, dict[str, str]] = {}
    for strategy, path in rubric_paths.items():
        path_ref = _portable_path_ref(path, repo_root=repo_root)
        if path_ref["kind"] != "repo_relative":
            raise ValueError(f"rubric must live inside the repository: {path}")
        refs[strategy] = {
            "path": path_ref["path"],
            "hash": _file_sha256(path),
        }
    return refs


def _evidence_engine_ref(
    backend_name: str, *, venv_python: str | None
) -> EvidenceEngineRefV1:
    """Resolve the exact evidence engine before any evidence query runs."""
    if backend_name == "nimare":
        return EvidenceEngineRefV1(
            name="nimare",
            version=importlib.metadata.version("nimare"),
            adapter="brain_researcher.autoresearch.society.evidence_backend.NimareBackend",
        )

    backend = NeuroLangBackend(corpus=None, venv_python=venv_python)
    proc = subprocess.run(
        [
            backend._venv_python,
            "-c",
            "import neurolang; print(neurolang.__version__)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    version = proc.stdout.strip()
    if proc.returncode != 0 or not version:
        detail = proc.stderr.strip()[:300] or f"exit {proc.returncode}"
        raise RuntimeError(
            "cannot seal NeuroLang engine identity before evidence execution: "
            f"{detail}"
        )
    return EvidenceEngineRefV1(
        name="neurolang",
        version=version,
        adapter="brain_researcher.autoresearch.society.evidence_backend.NeuroLangBackend",
    )


def build_demo_inputs(case: DemoCase = WORKING_MEMORY_CASE) -> DemoInputs:
    scope = ScopeBoundaryV1(
        modality="fMRI",
        datasets=["Neurosynth v7"],
        workflow_family="NeuroLang probabilistic-Datalog over Neurosynth",
    )
    claim = ClaimSpecV1(
        claim_id=case.claim_id,
        claim_text=case.claim_text,
        hypothesis_id=case.hypothesis_id,
        scope_boundary=scope,
        allowed_alternatives=list(case.rival_terms),
        success_criteria=case.success_criteria,
        failure_criteria=case.failure_criteria,
        confirmatory=True,
        extra={
            "demo_case": case.key,
            "evidence_claim_text": case.evidence_claim_text,
            "network_regions": list(case.network_regions),
            "rival_terms": list(case.rival_terms),
        },
    )
    hypothesis = HypothesisSpecV1(
        hypothesis_id=case.hypothesis_id,
        statement=case.hypothesis_statement,
        cause=case.cause,
        effect=case.effect,
        context=["coordinate-based fMRI meta-analysis", "Neurosynth v7"],
        predictions=list(case.predictions),
        alternative_explanations=list(case.rival_terms),
        critical_test=CriticalTestV1(
            manipulation=(
                f"compare {case.cause} studies with rival-overlapping studies removed "
                "and test multi-region coactivation"
            ),
            measurement=list(case.critical_test_measurements),
            comparison=case.critical_test_comparison,
        ),
    )
    return DemoInputs(claim=claim, hypothesis=hypothesis)


def _ceiling_from_verdict(
    verdict: EvidenceVerdict, *, display: str, rationale: str
) -> CeilingResult:
    return CeilingResult(
        status=verdict.status,
        display=display,
        rationale=rationale,
        inputs={
            "backend": verdict.backend,
            "profile": verdict.profile,
            "n_supporting": verdict.n_supporting,
            "raw": verdict.raw,
            "warnings": verdict.warnings,
        },
    )


def build_calibrated_claim_card(
    *,
    claim: ClaimSpecV1,
    hypothesis: HypothesisSpecV1,
    evidence: dict[str, EvidenceVerdict],
    evidence_bundle_refs: list[str],
    commitment: CommitmentCardV1,
    case: DemoCase = WORKING_MEMORY_CASE,
) -> tuple[ClaimCardV1, dict[str, Any]]:
    """Compose NeuroLang evidence axes into a Society ClaimCard.

    This is a demo adapter, not a new conductor path. It uses the existing
    ``CeilingResult`` + ``compose_ceilings`` law and records every axis in
    ``ClaimCardV1.extra['calibration']``.
    """
    if commitment.claim_id != claim.claim_id or not commitment.verify_hash():
        raise ValueError("commitment does not match the claim or its sealed content")
    axes = [
        claim_structure_ceiling(claim),
        reasoning_mode_ceiling(hypothesis),
        _ceiling_from_verdict(
            evidence["forward_default"],
            display="neurolang-forward-default",
            rationale="Default NeuroLang forward inference over Neurosynth.",
        ),
        _ceiling_from_verdict(
            evidence["forward_strict"],
            display="strict-evidence-profile",
            rationale=(
                "Same NeuroLang forward query under the conservative lift bar; this "
                "axis captures threshold fragility."
            ),
        ),
        _ceiling_from_verdict(
            evidence["specificity_excluding_rivals"],
            display=case.specificity_display,
            rationale=case.specificity_rationale,
        ),
        _ceiling_from_verdict(
            evidence["network_coactivation"],
            display=case.network_display,
            rationale=case.network_rationale,
        ),
    ]
    spine = compose_ceilings(axes)
    survived = [
        f"{axis.display}: {axis.status.value}"
        for axis in axes
        if axis.status is ClaimStatusV1.supported_within_scope
    ]
    capped = [
        f"{axis.display}: {axis.status.value} - {axis.rationale}"
        for axis in axes
        if axis.status is not ClaimStatusV1.supported_within_scope
    ]
    calibrated_text = case.calibrated_claim_text
    claim_card = ClaimCardV1(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        status=spine.status,
        scope_boundary=claim.scope_boundary,
        commitment_card_ref=commitment.commitment_id,
        commitment_hash=commitment.commitment_hash,
        evidence_bundle_refs=evidence_bundle_refs,
        survived_checks=survived,
        failed_checks=capped,
        falsification_budget_spent={
            "n_axes": len(axes),
            "axes": [axis.display for axis in axes],
            "note": "Demo calibration axes; no external falsifier population was run.",
        },
        next_required_evidence=list(case.next_required_evidence),
        pipeline_summary={
            "engine": "NeuroLangBackend",
            "claim_text_used_for_evidence": claim.extra["evidence_claim_text"],
            "network_regions": claim.extra["network_regions"],
            "rival_terms": claim.extra["rival_terms"],
        },
        status_not_ground_truth=True,
        extra={
            "calibration": {
                "binding_axis": spine.display,
                "binding_status": spine.status.value,
                "binding_rationale": spine.rationale,
                "axes": [
                    {
                        "display": axis.display,
                        "status": axis.status.value,
                        "rationale": axis.rationale,
                        "inputs": axis.inputs,
                    }
                    for axis in axes
                ],
                "calibrated_claim_text": calibrated_text,
                "multiverse_note": (
                    "Not applied: this demo calibrates a meta-analytic evidence claim, "
                    "not a dataset-specific contrast with a multiverse profile."
                ),
            }
        },
    )
    return claim_card, {
        "commitment_card": _model_dump(commitment),
        "axes": [_model_dump(axis) for axis in axes],
        "composed_ceiling": _model_dump(spine),
        "calibrated_claim_text": calibrated_text,
    }


def run_neurolang_evidence(
    *,
    corpus_path: Path,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    venv_python: str | None,
    case: DemoCase = WORKING_MEMORY_CASE,
    backend_name: str = "neurolang",
) -> dict[str, EvidenceVerdict]:
    corpus = load_neurosynth_corpus(str(corpus_path), data_dir=str(source_dir))
    backend: NeuroLangBackend | NimareBackend
    if backend_name == "nimare":
        backend = NimareBackend(corpus=corpus)
    else:
        backend = NeuroLangBackend(
            corpus=corpus, venv_python=venv_python, timeout_s=180
        )
    inputs = build_demo_inputs(case)
    claim_text = inputs.claim.extra["evidence_claim_text"]
    scope = inputs.claim.scope_boundary
    return {
        "forward_default": backend.verify(claim_text, scope, profile=DEFAULT_PROFILE),
        "forward_strict": backend.verify(claim_text, scope, profile=STRICT_PROFILE),
        "specificity_excluding_rivals": backend.verify_specificity(
            claim_text,
            scope,
            exclude_terms=list(inputs.claim.allowed_alternatives),
            profile=DEFAULT_PROFILE,
        ),
        "network_coactivation": backend.verify_network(
            claim_text,
            scope,
            regions=list(inputs.claim.extra["network_regions"]),
            profile=DEFAULT_PROFILE,
        ),
    }


def _markdown(bundle: dict[str, Any]) -> str:
    card = bundle["claim_card"]
    evidence = bundle["evidence_verdicts"]
    calibration = bundle["calibration"]

    def ascii_text(value: Any) -> str:
        return str(value).replace("\u2014", "-")

    rows = []
    for name, verdict in evidence.items():
        raw = verdict.get("raw") or {}
        rows.append(
            "| {name} | {status} | {lift} | {n} |".format(
                name=name,
                status=verdict["status"],
                lift=(
                    raw.get("lift")
                    or raw.get("lift_specific")
                    or raw.get("joint_forward_lift")
                    or ""
                ),
                n=verdict.get("n_supporting", ""),
            )
        )
    return "\n".join(
        [
            f"# {bundle['title']}",
            "",
            f"Generated: `{bundle['generated_at']}`",
            "",
            f"Claim card status: `{card['status']}`",
            "",
            "Boundary: this is a reproducible NeuroClaim / V-HRL audit artifact, not "
            "a NeuroProof certificate or proof ledger entry. It also does not bind a "
            "dataset-specific contrast to a multiverse profile.",
            "",
            "Calibrated claim:",
            "",
            f"> {calibration['calibrated_claim_text']}",
            "",
            "## Evidence Axes",
            "",
            "| axis | status | lift / joint lift | n |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
            "## Binding Axis",
            "",
            f"- `{calibration['composed_ceiling']['display']}`",
            f"- {ascii_text(calibration['composed_ceiling']['rationale'])}",
            "",
            "## Caveats",
            "",
            *[f"- {item}" for item in card["next_required_evidence"]],
            "",
            "## Reproduce",
            "",
            "Local light path -- standard scientific-Python only (NiMARE is the "
            "default backend; you do NOT need the full Brain Researcher platform):",
            "",
            "Run every command from the public repository root, not from this "
            "generated output directory:",
            "",
            "```bash",
            "git clone https://github.com/brain-researcher/brain-researcher-public.git",
            "cd brain-researcher-public",
            "python3.11 -m venv ~/.venvs/br-claim-repro",
            "source ~/.venvs/br-claim-repro/bin/activate",
            "python -m pip install -c reproducibility/auditable_claim_record/constraints-py311.txt "
            "-e . nimare nilearn",
            "python scripts/data/download_neurosynth_data.py",
            "python scripts/data/convert_neurosynth.py",
            "python scripts/autoresearch/run_auditable_claim_demo.py "
            f"--case {bundle['case_key']} \\",
            "  --corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl \\",
            "  --source-dir data/neurosynth_nimare/neurosynth_v7",
            "```",
            "",
            "The generator verifies the raw source manifest and the converted "
            "pickle provenance sidecar before querying evidence.",
            "",
            "Or, from the same repository root, use the language-driven path "
            "through the Brain Researcher MCP. A short hosted call sequence returns "
            "the gated verdict without starting local Brain Researcher services:",
            "",
            "```bash",
            "python reproducibility/auditable_claim_record/drive_from_language.py",
            "```",
            "",
            "NeuroLang is an optional *reference* engine only -- do NOT "
            "`pip install neurolang` (it is not installable from PyPI). The "
            "public checkout does not currently ship a verified installation "
            "recipe; see `reproducibility/auditable_claim_record/README.md` for "
            "that boundary.",
            "",
        ]
    )


def run_demo(
    *,
    corpus_path: Path,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_dir: Path,
    venv_python: str | None,
    case: DemoCase = WORKING_MEMORY_CASE,
    backend_name: str = "neurolang",
) -> dict[str, Any]:
    source_dir = source_dir.expanduser().resolve()
    converted_provenance = verify_converted_dataset(corpus_path, source_dir)
    source_manifest_path = source_dir / MANIFEST_FILENAME
    provenance_path = converted_provenance_path(corpus_path)
    inputs = build_demo_inputs(case)
    engine_ref = _evidence_engine_ref(backend_name, venv_python=venv_python)
    rubric_refs = _rubric_refs()
    commitment = lock_commitment(
        inputs.claim,
        attack_strategies=list(RUBRIC_PATHS),
        rubric_refs=rubric_refs,
        evidence_engine=engine_ref,
    )

    # Persist the sealed pre-observation contract before the first evidence
    # query. If execution later fails, this card remains an honest record of
    # what was committed rather than being synthesized after seeing results.
    output_dir.mkdir(parents=True, exist_ok=True)
    for post_observation_name in (
        "claim_card.json",
        "evidence_verdicts.json",
        "demo_bundle.json",
        "README.md",
    ):
        (output_dir / post_observation_name).unlink(missing_ok=True)
    _json_dump(output_dir / "commitment_card.json", _model_dump(commitment))

    evidence = run_neurolang_evidence(
        corpus_path=corpus_path,
        source_dir=source_dir,
        venv_python=venv_python,
        case=case,
        backend_name=backend_name,
    )
    evidence_json = {name: _model_dump(verdict) for name, verdict in evidence.items()}
    claim_card, calibration = build_calibrated_claim_card(
        claim=inputs.claim,
        hypothesis=inputs.hypothesis,
        evidence=evidence,
        evidence_bundle_refs=["evidence_verdicts.json"],
        commitment=commitment,
        case=case,
    )
    bundle = {
        "schema_version": "neurolang-vhrl-demo-bundle-v1",
        "case_key": case.key,
        "title": case.title,
        "generated_at": _utc_now(),
        "corpus_ref": {
            **_portable_path_ref(corpus_path),
            "sha256": _file_sha256(corpus_path),
            "verified_source": {
                "manifest": _portable_path_ref(source_manifest_path),
                "manifest_sha256": _file_sha256(source_manifest_path),
                "source_snapshot": converted_provenance["source_snapshot"],
                "source_commit": converted_provenance["source_commit"],
                "converted_provenance": _portable_path_ref(provenance_path),
                "converted_provenance_sha256": _file_sha256(provenance_path),
            },
        },
        "claim_spec": _model_dump(inputs.claim),
        "hypothesis_spec": _model_dump(inputs.hypothesis),
        "evidence_verdicts": evidence_json,
        "calibration": calibration,
        "claim_card": _model_dump(claim_card),
    }
    _json_dump(output_dir / "evidence_verdicts.json", evidence_json)
    _json_dump(output_dir / "claim_card.json", bundle["claim_card"])
    _json_dump(output_dir / "demo_bundle.json", bundle)
    (output_dir / "README.md").write_text(_markdown(bundle), encoding="utf-8")
    return bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        default=DEFAULT_CASE_KEY,
        choices=sorted(CASES),
        help="Demo case to run.",
    )
    parser.add_argument(
        "--corpus",
        default=os.environ.get("BR_NEUROCLAIM_CORPUS", DEFAULT_CORPUS),
        help="Path to the NiMARE Neurosynth dataset pickle.",
    )
    parser.add_argument(
        "--source-dir",
        default=os.environ.get("BR_NEUROCLAIM_SOURCE_DIR", str(DEFAULT_SOURCE_DIR)),
        help=(
            "Directory containing the pinned Neurosynth raw files and "
            "source_manifest.json associated with --corpus."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for demo JSON/Markdown artifacts. Defaults to the case output directory.",
    )
    parser.add_argument(
        "--venv-python",
        default=os.environ.get("BR_NEUROLANG_PYTHON"),
        help="Python interpreter for the isolated NeuroLang venv (neurolang backend only).",
    )
    parser.add_argument(
        "--backend",
        default=os.environ.get("BR_NEUROCLAIM_BACKEND", "nimare"),
        choices=["neurolang", "nimare"],
        help=(
            "Evidence backend. 'nimare' (default light path) runs in-process on the "
            "NiMARE/Neurosynth corpus with no extra interpreter; 'neurolang' uses the "
            "out-of-process probabilistic-Datalog engine (needs the NeuroLang venv)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    case = CASES[args.case]
    corpus_path = Path(os.path.expanduser(args.corpus)).resolve()
    source_dir = Path(os.path.expanduser(args.source_dir)).resolve()
    if not corpus_path.exists():
        raise SystemExit(
            f"Neurosynth corpus not found: {corpus_path}. Set BR_NEUROCLAIM_CORPUS or pass --corpus."
        )
    output_dir = Path(args.output_dir or case.output_dir)
    bundle = run_demo(
        corpus_path=corpus_path,
        source_dir=source_dir,
        output_dir=output_dir,
        venv_python=args.venv_python,
        case=case,
        backend_name=args.backend,
    )
    print(f"wrote {output_dir}")
    print(f"case={bundle['case_key']}")
    print(f"claim_card.status={bundle['claim_card']['status']}")
    print(f"binding_axis={bundle['calibration']['composed_ceiling']['display']}")


if __name__ == "__main__":
    main()
