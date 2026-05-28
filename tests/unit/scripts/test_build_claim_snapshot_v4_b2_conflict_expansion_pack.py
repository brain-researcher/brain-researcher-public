from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v4_b2_conflict_expansion_pack as module


def test_build_claim_snapshot_v4_b2_conflict_expansion_pack_materializes_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "_fetch_claim_rows_by_ids",
        lambda claim_ids: {
            "claim:support": {
                "claim_id": "claim:support",
                "paper_id": "paper:support",
                "target_id": "concept:attention",
                "polarity": "supports",
                "claim_text": "Top-down and bottom-up attention dissociate in memory.",
                "method_rigor": 0.4,
                "claim_strength": 0.7,
                "source": "gabriel",
                "run_id": "run:support",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.68,
            },
            "claim:refute": {
                "claim_id": "claim:refute",
                "paper_id": "paper:refute",
                "target_id": "concept:attention",
                "polarity": "refutes",
                "claim_text": "Top-down and bottom-up attention do not dissociate in memory.",
                "method_rigor": 0.4,
                "claim_strength": 0.7,
                "source": "gabriel",
                "run_id": "run:refute",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.68,
            },
        },
    )
    monkeypatch.setattr(
        module,
        "CURATED_FAMILIES",
        [
            {
                "family_key": "attention_conflict",
                "canonical_claim_id": "canonical_claim:attention_conflict",
                "target_id": "concept:attention",
                "target_type": "Concept",
                "claim_ids": ["claim:support", "claim:refute"],
                "family_label": "attention_conflict",
                "decision_reason": "curated conflict family",
                "failure_tags": ["polarity_or_antonym_confusion"],
            }
        ],
    )

    exit_code = module.main(["--output-dir", str(tmp_path / "out")])
    assert exit_code == 0

    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "claim_snapshot_v4_b2_conflict_expansion_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    assert {row["source_claim_id"] for row in rows} == {"claim:support", "claim:refute"}
    assert all(row["adjudicated_action"] == "retain_conflict_cluster_with_warning" for row in rows)
    assert all(row["snapshot_role"] == "conflict_cluster_warning" for row in rows)

    summary = json.loads(
        (tmp_path / "out" / "claim_snapshot_v4_b2_conflict_expansion_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"]["conflict_families_total"] == 1
    assert summary["counts"]["rows_total"] == 2


def test_build_claim_snapshot_v4_b2_conflict_expansion_pack_fails_on_target_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "_fetch_claim_rows_by_ids",
        lambda claim_ids: {
            "claim:support": {
                "claim_id": "claim:support",
                "paper_id": "paper:support",
                "target_id": "concept:attention",
                "polarity": "supports",
                "claim_text": "support text",
            },
            "claim:refute": {
                "claim_id": "claim:refute",
                "paper_id": "paper:refute",
                "target_id": "concept:working_memory",
                "polarity": "refutes",
                "claim_text": "refute text",
            },
        },
    )
    monkeypatch.setattr(
        module,
        "CURATED_FAMILIES",
        [
            {
                "family_key": "attention_conflict",
                "canonical_claim_id": "canonical_claim:attention_conflict",
                "target_id": "concept:attention",
                "target_type": "Concept",
                "claim_ids": ["claim:support", "claim:refute"],
                "family_label": "attention_conflict",
                "decision_reason": "curated conflict family",
                "failure_tags": ["polarity_or_antonym_confusion"],
            }
        ],
    )

    try:
        module.main(["--output-dir", str(tmp_path / "out")])
    except SystemExit as exc:
        assert "Fail-closed B2 conflict expansion mismatch" in str(exc)
    else:
        raise AssertionError("Expected fail-closed B2 conflict expansion mismatch")


def test_build_claim_snapshot_v4_b2_conflict_expansion_pack_hotloads_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "_fetch_target_claims",
        lambda target_ids: [
            {
                "claim_id": "claim:support",
                "paper_id": "paper:support",
                "target_id": "concept:attention",
                "polarity": "supports",
                "claim_text": "Top down attention shapes memory control.",
                "method_rigor": 0.41,
                "claim_strength": 0.76,
                "source": "gabriel",
                "run_id": "run:support",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.66,
            },
            {
                "claim_id": "claim:refute",
                "paper_id": "paper:refute",
                "target_id": "concept:attention",
                "polarity": "refutes",
                "claim_text": "Top down attention does not shape memory control.",
                "method_rigor": 0.39,
                "claim_strength": 0.73,
                "source": "gabriel",
                "run_id": "run:refute",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.65,
            },
        ],
    )
    monkeypatch.setattr(
        module,
        "_fetch_claim_rows_by_ids",
        lambda claim_ids: {
            "claim:support": {
                "claim_id": "claim:support",
                "paper_id": "paper:support",
                "target_id": "concept:attention",
                "polarity": "supports",
                "claim_text": "Top down attention shapes memory control.",
                "method_rigor": 0.41,
                "claim_strength": 0.76,
                "source": "gabriel",
                "run_id": "run:support",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.66,
            },
            "claim:refute": {
                "claim_id": "claim:refute",
                "paper_id": "paper:refute",
                "target_id": "concept:attention",
                "polarity": "refutes",
                "claim_text": "Top down attention does not shape memory control.",
                "method_rigor": 0.39,
                "claim_strength": 0.73,
                "source": "gabriel",
                "run_id": "run:refute",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.65,
            },
        },
    )

    exit_code = module.main(
        [
            "--output-dir",
            str(tmp_path / "out"),
            "--target-id",
            "concept:attention",
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (tmp_path / "out" / "claim_snapshot_v4_b2_conflict_expansion_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"]["conflict_families_total"] == 1
    assert summary["notes"]["hotload_target_ids_total"] == 1
    assert summary["resolved_families"][0]["target_id"] == "concept:attention"


def test_build_claim_snapshot_v4_b2_conflict_expansion_pack_excludes_existing_claim_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module,
        "_fetch_target_claims",
        lambda target_ids: [
            {
                "claim_id": "claim:old_support",
                "paper_id": "paper:old_support",
                "target_id": "concept:attention",
                "polarity": "supports",
                "claim_text": "Top down attention shapes memory control.",
                "method_rigor": 0.41,
                "claim_strength": 0.76,
                "source": "gabriel",
                "run_id": "run:old_support",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.66,
            },
            {
                "claim_id": "claim:old_refute",
                "paper_id": "paper:old_refute",
                "target_id": "concept:attention",
                "polarity": "refutes",
                "claim_text": "Top down attention does not shape memory control.",
                "method_rigor": 0.39,
                "claim_strength": 0.73,
                "source": "gabriel",
                "run_id": "run:old_refute",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.65,
            },
            {
                "claim_id": "claim:new_support",
                "paper_id": "paper:new_support",
                "target_id": "concept:attention",
                "polarity": "supports",
                "claim_text": "Top down attention supports episodic memory control.",
                "method_rigor": 0.41,
                "claim_strength": 0.71,
                "source": "gabriel",
                "run_id": "run:new_support",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.66,
            },
            {
                "claim_id": "claim:new_refute",
                "paper_id": "paper:new_refute",
                "target_id": "concept:attention",
                "polarity": "refutes",
                "claim_text": "Top down attention does not support episodic memory control.",
                "method_rigor": 0.39,
                "claim_strength": 0.7,
                "source": "gabriel",
                "run_id": "run:new_refute",
                "rel_source": "gabriel",
                "evidence_quality_score": 0.65,
            },
        ],
    )
    monkeypatch.setattr(
        module,
        "_fetch_claim_rows_by_ids",
        lambda claim_ids: {
            claim_id: {
                "claim_id": claim_id,
                "paper_id": claim_id.replace("claim:", "paper:"),
                "target_id": "concept:attention",
                "polarity": "supports" if "support" in claim_id else "refutes",
                "claim_text": claim_id,
                "method_rigor": 0.4,
                "claim_strength": 0.7,
                "source": "gabriel",
                "run_id": claim_id.replace("claim:", "run:"),
                "rel_source": "gabriel",
                "evidence_quality_score": 0.65,
            }
            for claim_id in claim_ids
        },
    )
    exclude_pack = tmp_path / "exclude.jsonl"
    exclude_pack.write_text(
        json.dumps({"source_claim_id": "claim:old_support"}) + "\n"
        + json.dumps({"source_claim_id": "claim:old_refute"}) + "\n",
        encoding="utf-8",
    )

    exit_code = module.main(
        [
            "--output-dir",
            str(tmp_path / "out"),
            "--target-id",
            "concept:attention",
            "--exclude-pack-jsonl",
            str(exclude_pack),
        ]
    )
    assert exit_code == 0

    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "claim_snapshot_v4_b2_conflict_expansion_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert {row["source_claim_id"] for row in rows} == {"claim:new_support", "claim:new_refute"}
