#!/usr/bin/env python3
"""Build a larger but still bounded pre-Gate-B bootstrap claim benchmark."""

from __future__ import annotations

import copy
import json
from pathlib import Path

try:
    from .build_claim_bootstrap_v2 import (
        BOOTSTRAP_NOTE,
        MANIFEST_STATUS,
        ROOT,
        SOURCE_SPECS as V2_SOURCE_SPECS,
        SourceSpec,
        _allowed_node_types,
        _seed_manifest_row,
        _source_manifest_row,
        _write_jsonl,
        build_manifests as build_v2_manifests,
        load_source,
    )
except ImportError:
    from build_claim_bootstrap_v2 import (
        BOOTSTRAP_NOTE,
        MANIFEST_STATUS,
        ROOT,
        SOURCE_SPECS as V2_SOURCE_SPECS,
        SourceSpec,
        _allowed_node_types,
        _seed_manifest_row,
        _source_manifest_row,
        _write_jsonl,
        build_manifests as build_v2_manifests,
        load_source,
    )

SAMPLE_OUTPUT = ROOT / "tests/fixtures/br-kg/gabriel_measurements.bootstrap_v3_lite.jsonl"
CALIBRATION_OUTPUT = ROOT / "docs/planning/claim_hypotheses_calibration_v3_lite.jsonl"
HELDOUT_OUTPUT = ROOT / "docs/planning/claim_hypotheses_heldout_v3_lite.jsonl"

CALIBRATION_VERSION = "claim_hypotheses_calibration_v3_lite"
HELDOUT_VERSION = "claim_hypotheses_heldout_v3_lite"
BOOTSTRAP_NOTE_V3 = BOOTSTRAP_NOTE.replace("v2", "v3-lite")

SOURCE_SPECS: dict[str, SourceSpec] = {
    **V2_SOURCE_SPECS,
    "amygdala_reward_support": SourceSpec(
        key="amygdala_reward_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-gemini-sdk-batch100-off100-20260225_013625/shards/shard_0000.jsonl",
        line_number=14,
        expected_paper_id="paper:10_1016_j_biopsych_2017_08_020",
        expected_target_id="concept:amygdala_reward_reactivity",
        expected_claim_id="claim:b16751b473f09874df8053775fbb35f0",
        expected_span_id="evidence:f09ccf121b6104648c1e91dc2b2ac945",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=9,
    ),
    "locus_coeruleus_support": SourceSpec(
        key="locus_coeruleus_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-gemini-sdk-batch100-off100-20260225_013625/shards/shard_0000.jsonl",
        line_number=15,
        expected_paper_id="paper:10_1016_j_biopsych_2017_08_021",
        expected_target_id="region:locus_coeruleus",
        expected_claim_id="claim:7b858b2e0cfe374856830def8df4a681",
        expected_span_id="evidence:4dc1ecf18c9949ae848fddda1b4a24e6",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=10,
    ),
    "mpcc_support": SourceSpec(
        key="mpcc_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-gemini-sdk-batch100-off100-20260225_013625/shards/shard_0000.jsonl",
        line_number=17,
        expected_paper_id="paper:10_1016_j_biopsycho_2018_02_018",
        expected_target_id="region:medial_posterior_cingulate",
        expected_claim_id="claim:7a8efe1e555248f8e432e37a6515b852",
        expected_span_id="evidence:82d1cb744c8df237c6b6ea52c00451f0",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=11,
    ),
    "tpj_support": SourceSpec(
        key="tpj_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-gemini-sdk-batch100-off100-20260225_013625/shards/shard_0004.jsonl",
        line_number=15,
        expected_paper_id="paper:10_1016_j_neuroimage_2017_09_064",
        expected_target_id="region:temporoparietal_junction",
        expected_claim_id="claim:28fcbcec2470e0c24db5a5fc716143cc",
        expected_span_id="evidence:71a0b6f8880ee62eb35546dcf90d2e91",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=12,
    ),
    "amygdala_support": SourceSpec(
        key="amygdala_support",
        path="data/br-kg/raw/gabriel/runs/gabriel-gemini-sdk-batch100-off100-20260225_013625/shards/shard_0004.jsonl",
        line_number=17,
        expected_paper_id="paper:10_1016_j_neuroimage_2017_10_031",
        expected_target_id="region:amygdala",
        expected_claim_id="claim:872fcaaffec17ba363216ac5eb04c317",
        expected_span_id="evidence:ef07b8a82a443b5a104ee04a66928165",
        gate_profile="kg_bootstrap",
        gate_pass=True,
        review_status="accepted_bootstrap",
        sample_order=13,
    ),
}


def _retag_rows(rows: list[dict[str, object]], version: str) -> list[dict[str, object]]:
    retagged: list[dict[str, object]] = []
    for row in rows:
        cloned = copy.deepcopy(row)
        cloned["benchmark_version"] = version
        notes = str(cloned.get("notes") or "")
        if notes:
            cloned["notes"] = notes.replace("v2", "v3-lite")
        retagged.append(cloned)
    return retagged


def _supported_row(source, version: str, *, note_suffix: str) -> dict[str, object]:
    row = _seed_manifest_row(source, version)
    row["notes"] = (
        f"{BOOTSTRAP_NOTE_V3} Added in v3-lite from "
        f"{source.spec.path}:{source.spec.line_number}. {note_suffix}"
    )
    return row


def build_manifests(selected: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    calibration, heldout = build_v2_manifests(selected)
    calibration = _retag_rows(calibration, CALIBRATION_VERSION)
    heldout = _retag_rows(heldout, HELDOUT_VERSION)

    calibration.extend(
        [
            _supported_row(
                selected["locus_coeruleus_support"],
                CALIBRATION_VERSION,
                note_suffix="Exact region/title match with auditable one-span support.",
            ),
            _supported_row(
                selected["tpj_support"],
                CALIBRATION_VERSION,
                note_suffix="Specific TPJ support seed retained as a clean region-level calibration case.",
            ),
            _supported_row(
                selected["amygdala_reward_support"],
                CALIBRATION_VERSION,
                note_suffix="Composite concept seed kept because the claim and span are literal and auditable.",
            ),
        ]
    )

    heldout.extend(
        [
            _supported_row(
                selected["amygdala_support"],
                HELDOUT_VERSION,
                note_suffix="Held-out support case added after v3-lite audit; intervention-specific but directly anchored.",
            ),
            _supported_row(
                selected["mpcc_support"],
                HELDOUT_VERSION,
                note_suffix="Used as the audited reserve support replacement after dropping the weak precuneus refute row.",
            ),
        ]
    )

    return calibration, heldout


def main() -> None:
    selected = {
        key: load_source(spec)
        for key, spec in sorted(SOURCE_SPECS.items(), key=lambda item: item[1].sample_order)
    }

    sample_rows = [
        copy.deepcopy(selected[key].record)
        for key in [
            spec.key
            for spec in sorted(SOURCE_SPECS.values(), key=lambda spec: spec.sample_order)
        ]
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
        "notes": [
            "v3-lite excludes the weak unauditable precuneus refute row.",
            "v3-lite adds only audited support seeds beyond the v2 mixed/conflicting baseline.",
        ],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
