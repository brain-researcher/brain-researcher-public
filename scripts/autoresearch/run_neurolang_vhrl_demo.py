#!/usr/bin/env python
"""Generate NeuroLang -> V-HRL calibrated ClaimCard demo artifacts.

This script is intentionally narrow and rerunnable. It reads a local NiMARE
Neurosynth corpus, runs the out-of-process NeuroLang backend, and writes a JSON
bundle plus a Markdown summary under ``docs/results/`` by default.

Inputs:
  --corpus: NiMARE Neurosynth dataset pickle. Defaults to BR_NEUROCLAIM_CORPUS or
    ``~/.nimare/neurosynth/neurosynth_terms_dataset.pkl.gz``.
  --case: demo case to run. Defaults to ``working_memory``.
  --output-dir: output directory. Defaults to the selected case's result folder.
  --venv-python: optional NeuroLang Python interpreter. Defaults to
    BR_NEUROLANG_PYTHON or ``~/.venvs/neurolang-py312/bin/python``.

Outputs:
  evidence_verdicts.json
  claim_card.json
  demo_bundle.json
  README.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
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
    ScopeBoundaryV1,
    lock_commitment,
)
from brain_researcher.autoresearch.society.corpus import load_neurosynth_corpus
from brain_researcher.autoresearch.society.evidence_backend import (
    DEFAULT_PROFILE,
    STRICT_PROFILE,
    EvidenceVerdict,
    NeuroLangBackend,
)
from brain_researcher.autoresearch.society.hypotheses import (
    CriticalTestV1,
    HypothesisSpecV1,
    reasoning_mode_ceiling,
)
from brain_researcher.autoresearch.society.multiverse import CeilingResult

DEFAULT_CORPUS = "~/.nimare/neurosynth/neurosynth_terms_dataset.pkl.gz"
DEFAULT_CASE_KEY = "working_memory"


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
    return datetime.now(timezone.utc).isoformat()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    commitment_rubric_refs: dict[str, dict[str, str]],
    case: DemoCase = WORKING_MEMORY_CASE,
) -> tuple[ClaimCardV1, dict[str, Any]]:
    """Compose NeuroLang evidence axes into a Society ClaimCard.

    This is a demo adapter, not a new conductor path. It uses the existing
    ``CeilingResult`` + ``compose_ceilings`` law and records every axis in
    ``ClaimCardV1.extra['calibration']``.
    """
    commitment = lock_commitment(
        claim,
        attack_strategies=[
            "strict_evidence_profile",
            "compositional_specificity",
            "network_coactivation",
        ],
        rubric_refs=commitment_rubric_refs,
    )
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
    venv_python: str | None,
    case: DemoCase = WORKING_MEMORY_CASE,
) -> dict[str, EvidenceVerdict]:
    corpus = load_neurosynth_corpus(str(corpus_path))
    backend = NeuroLangBackend(corpus=corpus, venv_python=venv_python, timeout_s=180)
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
            "```bash",
            "source ${HOME}/miniconda3/etc/profile.d/conda.sh",
            "conda activate brain_researcher",
            "PYTHONPATH=src BR_NEUROLANG_PYTHON=$HOME/.venvs/neurolang-py312/bin/python "
            f"python scripts/autoresearch/run_neurolang_vhrl_demo.py --case {bundle['case_key']}",
            "```",
            "",
        ]
    )


def run_demo(
    *,
    corpus_path: Path,
    output_dir: Path,
    venv_python: str | None,
    case: DemoCase = WORKING_MEMORY_CASE,
) -> dict[str, Any]:
    inputs = build_demo_inputs(case)
    evidence = run_neurolang_evidence(
        corpus_path=corpus_path, venv_python=venv_python, case=case
    )
    evidence_json = {name: _model_dump(verdict) for name, verdict in evidence.items()}
    script_path = Path(__file__).resolve()
    rubric_refs = {
        "strict_evidence_profile": {
            "path": str(script_path),
            "hash": _file_sha256(script_path),
        },
        "compositional_specificity": {
            "path": str(script_path),
            "hash": _file_sha256(script_path),
        },
        "network_coactivation": {
            "path": str(script_path),
            "hash": _file_sha256(script_path),
        },
    }
    claim_card, calibration = build_calibrated_claim_card(
        claim=inputs.claim,
        hypothesis=inputs.hypothesis,
        evidence=evidence,
        evidence_bundle_refs=["evidence_verdicts.json"],
        commitment_rubric_refs=rubric_refs,
        case=case,
    )
    bundle = {
        "schema_version": "neurolang-vhrl-demo-bundle-v1",
        "case_key": case.key,
        "title": case.title,
        "generated_at": _utc_now(),
        "corpus_path": str(corpus_path),
        "claim_spec": _model_dump(inputs.claim),
        "hypothesis_spec": _model_dump(inputs.hypothesis),
        "evidence_verdicts": evidence_json,
        "calibration": calibration,
        "claim_card": _model_dump(claim_card),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
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
        "--output-dir",
        default=None,
        help="Directory for demo JSON/Markdown artifacts. Defaults to the case output directory.",
    )
    parser.add_argument(
        "--venv-python",
        default=os.environ.get("BR_NEUROLANG_PYTHON"),
        help="Python interpreter for the isolated NeuroLang venv.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    case = CASES[args.case]
    corpus_path = Path(os.path.expanduser(args.corpus)).resolve()
    if not corpus_path.exists():
        raise SystemExit(
            f"Neurosynth corpus not found: {corpus_path}. Set BR_NEUROCLAIM_CORPUS or pass --corpus."
        )
    output_dir = Path(args.output_dir or case.output_dir)
    bundle = run_demo(
        corpus_path=corpus_path,
        output_dir=output_dir,
        venv_python=args.venv_python,
        case=case,
    )
    print(f"wrote {output_dir}")
    print(f"case={bundle['case_key']}")
    print(f"claim_card.status={bundle['claim_card']['status']}")
    print(f"binding_axis={bundle['calibration']['composed_ceiling']['display']}")


if __name__ == "__main__":
    main()
