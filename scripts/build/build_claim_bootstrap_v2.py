#!/usr/bin/env python3
"""Build bounded v2 bootstrap claim artifacts from fixed GABRIEL source records."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (
    DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    GabrielVariables,
    compute_gabriel_variables,
    evaluate_high_precision_gate,
)

ROOT = Path(__file__).resolve().parents[2]

SAMPLE_OUTPUT = ROOT / "tests/fixtures/br-kg/gabriel_measurements.bootstrap_v2.jsonl"
CALIBRATION_OUTPUT = (
    ROOT / "docs/planning/claim_hypotheses_calibration_v2.jsonl"
)
HELDOUT_OUTPUT = ROOT / "docs/planning/claim_hypotheses_heldout_v2.jsonl"

MANIFEST_STATUS = "bootstrap_only_pre_gate_b"
BOOTSTRAP_NOTE = (
    "Bootstrap-only v2 artifact assembled from fixed GABRIEL source records. "
    "This set is pre-Gate-B and must not be used for headline benchmark claims."
)


@dataclass(frozen=True)
class SourceSpec:
    key: str
    path: str
    line_number: int
    expected_paper_id: str
    expected_target_id: str | None
    expected_claim_id: str | None
    expected_span_id: str | None
    gate_profile: str
    gate_pass: bool
    review_status: str
    sample_order: int


@dataclass(frozen=True)
class LoadedSource:
    spec: SourceSpec
    record: dict[str, Any]
    variables: GabrielVariables
    accepted: bool
    reasons: list[str]

    @property
    def paper_id(self) -> str:
        return str((self.record.get("paper") or {}).get("id") or "")

    @property
    def target_id(self) -> str:
        return str((self.record.get("target") or {}).get("id") or "")

    @property
    def target_label(self) -> str:
        return str((self.record.get("target") or {}).get("label") or "")

    @property
    def target_type(self) -> str:
        return str((self.record.get("target") or {}).get("type") or "")

    @property
    def claim_id(self) -> str:
        return str((self.record.get("claim") or {}).get("id") or "")

    @property
    def claim_text(self) -> str:
        return str((self.record.get("claim") or {}).get("text") or "")

    @property
    def claim_polarity(self) -> str:
        return str((self.record.get("claim") or {}).get("polarity") or "")

    @property
    def evidence_span_id(self) -> str:
        return str((self.record.get("evidence") or {}).get("span_id") or "")

    @property
    def paper_title(self) -> str:
        return str((self.record.get("paper") or {}).get("title") or "")


SOURCE_SPECS: dict[str, SourceSpec] = {
    "wm_seed": SourceSpec(
        key="wm_seed",
        path="data/br-kg/raw/gabriel/measurements.jsonl",
        line_number=1,
        expected_paper_id="pmid:40000001",
        expected_target_id="concept:working_memory",
        expected_claim_id="claim:wm_dlpfc",
        expected_span_id="evidence:wm_dlpfc_1",
        gate_profile="high_precision",
        gate_pass=True,
        review_status="accepted_high_precision",
        sample_order=1,
    ),
    "lcont7_seed": SourceSpec(
        key="lcont7_seed",
        path="data/br-kg/raw/gabriel/measurements.jsonl",
        line_number=2,
        expected_paper_id="pmid:40000002",
        expected_target_id="schaefer400-7n:L_Cont_7",
        expected_claim_id="claim:conflict_lcont7",
        expected_span_id="evidence:conflict_lcont7_1",
        gate_profile="high_precision",
        gate_pass=True,
        review_status="accepted_high_precision",
        sample_order=2,
    ),
    "rejected_exec_control": SourceSpec(
        key="rejected_exec_control",
        path="data/br-kg/raw/gabriel/measurements.jsonl",
        line_number=3,
        expected_paper_id="pmid:40000003",
        expected_target_id=None,
        expected_claim_id=None,
        expected_span_id=None,
        gate_profile="kg_bootstrap",
        gate_pass=False,
        review_status="review_queue_expected",
        sample_order=3,
    ),
    "attention_refute": SourceSpec(
        key="attention_refute",
        path="data/br-kg/raw/gabriel/runs/gabriel-pubget-smoke-20260225/shards/shard_0000.jsonl",
        line_number=1,
        expected_paper_id="pmid:41446878",
        expected_target_id="concept:attention",
        expected_claim_id="claim:592e21efcf95e2cb37890b1bd835ef03",
        expected_span_id="evidence:18f1fa767f6fa44f1e3b422769e4e056",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=4,
    ),
    "insula_support": SourceSpec(
        key="insula_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-pubget-smoke-20260225/shards/shard_0000.jsonl",
        line_number=2,
        expected_paper_id="pmid:41446119",
        expected_target_id="region:insula",
        expected_claim_id="claim:bcbf3a40052599b6c72c9a7c38585e6f",
        expected_span_id="evidence:e96a206515599d99ab6ae5a46c2c73f5",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=5,
    ),
    "default_mode_refute": SourceSpec(
        key="default_mode_refute",
        path="data/br-kg/raw/gabriel/runs/gabriel-pubget-smoke-20260225/shards/shard_0000.jsonl",
        line_number=3,
        expected_paper_id="pmid:41442573",
        expected_target_id="concept:default_mode_network",
        expected_claim_id="claim:028fee000c3903b1e325ecc2bbaf4286",
        expected_span_id="evidence:c6fe6b30d79167724b32842e489f5f83",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=6,
    ),
    "attention_support": SourceSpec(
        key="attention_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-gemini-sdk-batch100-off100-20260225_013625/shards/shard_0000.jsonl",
        line_number=9,
        expected_paper_id="paper:10_1016_j_bbr_2018_02_031",
        expected_target_id="concept:attention",
        expected_claim_id="claim:08d8acd1a4f1cc397140594f824bab95",
        expected_span_id="evidence:c67bf80bd8cbca078f57f51bfc9ca535",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=7,
    ),
    "response_inhibition_support": SourceSpec(
        key="response_inhibition_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-gemini-sdk-batch100-off100-20260225_013625/shards/shard_0004.jsonl",
        line_number=8,
        expected_paper_id="paper:10_1016_j_neurobiolaging_2018_02_003",
        expected_target_id="task:response_inhibition",
        expected_claim_id="claim:88f2eb8941c9228d0071651be108fa58",
        expected_span_id="evidence:da661877c7af6705b8a8a704632d63b2",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=8,
    ),
}


def _read_jsonl_record(path: Path, line_number: int) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        for current, raw in enumerate(handle, start=1):
            if current == line_number:
                return json.loads(raw)
    raise ValueError(f"{path} does not contain line {line_number}")


def _gate_thresholds(profile: str) -> dict[str, Any]:
    try:
        return GabrielMeasurementLoader.QUALITY_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown gate profile: {profile}") from exc


def load_source(spec: SourceSpec) -> LoadedSource:
    path = ROOT / spec.path
    record = _read_jsonl_record(path, spec.line_number)

    paper_id = str((record.get("paper") or {}).get("id") or "")
    if paper_id != spec.expected_paper_id:
        raise ValueError(
            f"{spec.key}: paper mismatch, expected {spec.expected_paper_id}, got {paper_id}"
        )

    target_id = str((record.get("target") or {}).get("id") or "")
    if spec.expected_target_id is not None and target_id != spec.expected_target_id:
        raise ValueError(
            f"{spec.key}: target mismatch, expected {spec.expected_target_id}, got {target_id}"
        )

    claim_id = str((record.get("claim") or {}).get("id") or "")
    if spec.expected_claim_id is not None and claim_id != spec.expected_claim_id:
        raise ValueError(
            f"{spec.key}: claim mismatch, expected {spec.expected_claim_id}, got {claim_id}"
        )

    span_id = str((record.get("evidence") or {}).get("span_id") or "")
    if spec.expected_span_id is not None and span_id != spec.expected_span_id:
        raise ValueError(
            f"{spec.key}: span mismatch, expected {spec.expected_span_id}, got {span_id}"
        )

    variables = compute_gabriel_variables(record, DEFAULT_REQUIRED_PROVENANCE_FIELDS)
    accepted, reasons = evaluate_high_precision_gate(
        variables, thresholds=_gate_thresholds(spec.gate_profile)
    )
    if accepted != spec.gate_pass:
        raise ValueError(
            f"{spec.key}: gate {spec.gate_profile} expected pass={spec.gate_pass}, got {accepted} ({reasons})"
        )

    return LoadedSource(
        spec=spec,
        record=record,
        variables=variables,
        accepted=accepted,
        reasons=reasons,
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=False))
            handle.write("\n")


def _source_manifest_row(source: LoadedSource) -> dict[str, Any]:
    return {
        "path": source.spec.path,
        "line_number": source.spec.line_number,
        "paper_id": source.paper_id,
        "target_id": source.target_id or None,
        "target_type": source.target_type or None,
        "claim_id": source.claim_id or None,
        "span_id": source.evidence_span_id or None,
        "polarity": source.claim_polarity or None,
        "gate_profile": source.spec.gate_profile,
        "accepted_under_gate": source.accepted,
        "rejection_reasons": source.reasons,
        "review_status": source.spec.review_status,
    }


def _allowed_node_types(source: LoadedSource) -> list[str]:
    target_type = source.target_type.strip()
    if not target_type:
        return ["Concept"]
    return [target_type]


def _seed_manifest_row(source: LoadedSource, benchmark_version: str) -> dict[str, Any]:
    notes = (
        f"{BOOTSTRAP_NOTE} Preserved v1 seed from {source.spec.path}:{source.spec.line_number}."
    )
    return {
        "benchmark_version": benchmark_version,
        "manifest_status": MANIFEST_STATUS,
        "bootstrap_only": True,
        "hypothesis_id": source.claim_id or source.paper_id,
        "text": source.claim_text,
        "entity_hints": [value for value in [source.target_id, source.target_label] if value],
        "allowed_node_types": _allowed_node_types(source),
        "expected_verdict": "supported",
        "expected_anchor_entities": [
            value
            for value in [source.target_id, source.claim_id, source.evidence_span_id]
            if value
        ],
        "expected_supporting_publications": [source.paper_id],
        "expected_conflicting_publications": [],
        "source_records": [_source_manifest_row(source)],
        "review_status": source.spec.review_status,
        "notes": notes,
    }


def build_manifests(selected: dict[str, LoadedSource]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calibration_version = "claim_hypotheses_calibration_v2"
    heldout_version = "claim_hypotheses_heldout_v2"

    wm_seed = selected["wm_seed"]
    lcont7_seed = selected["lcont7_seed"]
    rejected_exec_control = selected["rejected_exec_control"]
    insula_support = selected["insula_support"]
    attention_support = selected["attention_support"]
    attention_refute = selected["attention_refute"]
    default_mode_refute = selected["default_mode_refute"]
    response_inhibition_support = selected["response_inhibition_support"]

    calibration = [
        _seed_manifest_row(wm_seed, calibration_version),
        {
            "benchmark_version": calibration_version,
            "manifest_status": MANIFEST_STATUS,
            "bootstrap_only": True,
            "hypothesis_id": lcont7_seed.claim_id,
            "text": "Left control network parcel L_Cont_7 shows corrected activation.",
            "entity_hints": [
                value
                for value in [lcont7_seed.target_id, lcont7_seed.target_label]
                if value
            ],
            "allowed_node_types": _allowed_node_types(lcont7_seed),
            "expected_verdict": "supported",
            "expected_anchor_entities": [
                value
                for value in [
                    lcont7_seed.target_id,
                    lcont7_seed.claim_id,
                    lcont7_seed.evidence_span_id,
                ]
                if value
            ],
            "expected_supporting_publications": [lcont7_seed.paper_id],
            "expected_conflicting_publications": [],
            "source_records": [_source_manifest_row(lcont7_seed)],
            "review_status": lcont7_seed.spec.review_status,
            "notes": (
                f"{BOOTSTRAP_NOTE} Preserved v1 high-precision region seed from "
                f"{lcont7_seed.spec.path}:{lcont7_seed.spec.line_number}, but rewrote "
                "the benchmark text to stay single-entity and avoid task-triggered union fallback."
            ),
        },
        {
            "benchmark_version": calibration_version,
            "manifest_status": MANIFEST_STATUS,
            "bootstrap_only": True,
            "hypothesis_id": response_inhibition_support.claim_id,
            "text": response_inhibition_support.claim_text,
            "entity_hints": [
                value
                for value in [
                    response_inhibition_support.target_id,
                    response_inhibition_support.target_label,
                    "Levodopa",
                ]
                if value
            ],
            "allowed_node_types": _allowed_node_types(response_inhibition_support),
            "expected_verdict": "supported",
            "expected_anchor_entities": [
                value
                for value in [
                    response_inhibition_support.target_id,
                    response_inhibition_support.claim_id,
                    response_inhibition_support.evidence_span_id,
                ]
                if value
            ],
            "expected_supporting_publications": [response_inhibition_support.paper_id],
            "expected_conflicting_publications": [],
            "source_records": [_source_manifest_row(response_inhibition_support)],
            "review_status": response_inhibition_support.spec.review_status,
            "notes": (
                f"{BOOTSTRAP_NOTE} Additional accepted `kg_bootstrap` support seed "
                f"from {response_inhibition_support.spec.path}:{response_inhibition_support.spec.line_number}."
            ),
        },
    ]

    heldout = [
        {
            "benchmark_version": heldout_version,
            "manifest_status": MANIFEST_STATUS,
            "bootstrap_only": True,
            "hypothesis_id": rejected_exec_control.paper_id,
            "text": str((rejected_exec_control.record.get("claim") or {}).get("text") or ""),
            "entity_hints": ["Executive Control"],
            "allowed_node_types": ["Concept"],
            "expected_verdict": "insufficient_evidence",
            "expected_anchor_entities": ["Executive Control"],
            "expected_supporting_publications": [],
            "expected_conflicting_publications": [],
            "source_records": [_source_manifest_row(rejected_exec_control)],
            "review_status": rejected_exec_control.spec.review_status,
            "notes": (
                f"{BOOTSTRAP_NOTE} Retained rejected seed. "
                f"`{rejected_exec_control.paper_id}` remains rejected under "
                f"`kg_bootstrap` because {', '.join(rejected_exec_control.reasons)}."
            ),
        },
        {
            "benchmark_version": heldout_version,
            "manifest_status": MANIFEST_STATUS,
            "bootstrap_only": True,
            "hypothesis_id": "bootstrap:attention_mixed",
            "text": "Attention effects are uniformly positive across the bounded bootstrap sample.",
            "entity_hints": ["concept:attention", "Attention"],
            "allowed_node_types": ["Concept"],
            "expected_verdict": "mixed",
            "expected_anchor_entities": [
                "concept:attention",
                attention_support.claim_id,
                attention_refute.claim_id,
                attention_support.evidence_span_id,
                attention_refute.evidence_span_id,
            ],
            "expected_supporting_publications": [attention_support.paper_id],
            "expected_conflicting_publications": [attention_refute.paper_id],
            "source_records": [
                _source_manifest_row(attention_support),
                _source_manifest_row(attention_refute),
            ],
            "review_status": "accepted_bootstrap_adjudicated_mixed",
            "notes": (
                f"{BOOTSTRAP_NOTE} Real mixed candidate built from one accepted "
                f"`concept:attention` support shard and one accepted "
                f"`concept:attention` refute shard."
            ),
        },
        {
            "benchmark_version": heldout_version,
            "manifest_status": MANIFEST_STATUS,
            "bootstrap_only": True,
            "hypothesis_id": "bootstrap:default_mode_network_conflicting",
            "text": "Default mode network connectivity remains unchanged across lifespan and Alzheimer's disease cohorts.",
            "entity_hints": [
                "concept:default_mode_network",
                "Default Mode Network",
            ],
            "allowed_node_types": ["Concept"],
            "expected_verdict": "conflicting",
            "expected_anchor_entities": [
                "concept:default_mode_network",
                default_mode_refute.claim_id,
                default_mode_refute.evidence_span_id,
            ],
            "expected_supporting_publications": [],
            "expected_conflicting_publications": [default_mode_refute.paper_id],
            "source_records": [_source_manifest_row(default_mode_refute)],
            "review_status": "accepted_bootstrap_adjudicated_conflicting",
            "notes": (
                f"{BOOTSTRAP_NOTE} True conflicting case derived from an accepted "
                f"`kg_bootstrap` refute record for `concept:default_mode_network`."
            ),
        },
        {
            "benchmark_version": heldout_version,
            "manifest_status": MANIFEST_STATUS,
            "bootstrap_only": True,
            "hypothesis_id": insula_support.claim_id,
            "text": insula_support.claim_text,
            "entity_hints": [
                value
                for value in [insula_support.target_id, insula_support.target_label] if value
            ],
            "allowed_node_types": _allowed_node_types(insula_support),
            "expected_verdict": "supported",
            "expected_anchor_entities": [
                value
                for value in [
                    insula_support.target_id,
                    insula_support.claim_id,
                    insula_support.evidence_span_id,
                ]
                if value
            ],
            "expected_supporting_publications": [insula_support.paper_id],
            "expected_conflicting_publications": [],
            "source_records": [_source_manifest_row(insula_support)],
            "review_status": insula_support.spec.review_status,
            "notes": (
                f"{BOOTSTRAP_NOTE} Additional accepted `kg_bootstrap` support case "
                f"for `region:insula`."
            ),
        },
    ]

    return calibration, heldout


def main() -> None:
    selected = {
        key: load_source(spec)
        for key, spec in sorted(SOURCE_SPECS.items(), key=lambda item: item[1].sample_order)
    }

    sample_rows = [
        copy.deepcopy(selected[key].record)
        for key in [spec.key for spec in sorted(SOURCE_SPECS.values(), key=lambda spec: spec.sample_order)]
    ]
    calibration_rows, heldout_rows = build_manifests(selected)

    _write_jsonl(SAMPLE_OUTPUT, sample_rows)
    _write_jsonl(CALIBRATION_OUTPUT, calibration_rows)
    _write_jsonl(HELDOUT_OUTPUT, heldout_rows)

    summary = {
        "sample_output": str(SAMPLE_OUTPUT.relative_to(ROOT)),
        "sample_records": len(sample_rows),
        "calibration_output": str(CALIBRATION_OUTPUT.relative_to(ROOT)),
        "calibration_records": len(calibration_rows),
        "heldout_output": str(HELDOUT_OUTPUT.relative_to(ROOT)),
        "heldout_records": len(heldout_rows),
        "heldout_expected_verdicts": [
            row["expected_verdict"] for row in heldout_rows
        ],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
