from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_substantive_breadth_pack as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_substantive_breadth_pack_projects_post_gap_counts(
    tmp_path: Path,
) -> None:
    snapshot_v2 = tmp_path / "claim_snapshot_v2.jsonl"
    warning_gap = tmp_path / "warning_conflict_gap_pack.jsonl"
    accepted = tmp_path / "accepted_records.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(
        snapshot_v2,
        [
            {
                "source_claim_id": "claim:base",
                "paper_id": "paper:base",
                "target_id": "concept:working_memory",
                "target_type": "Concept",
                "claim_text": "Working memory load robustly recruits dlPFC.",
                "polarity": "supports",
                "canonical_claim_id": module._canonical_claim_id(
                    target_id="concept:working_memory",
                    target_type="Concept",
                    claim_text="Working memory load robustly recruits dlPFC.",
                    polarity="supports",
                ),
            }
        ],
    )
    _write_jsonl(
        warning_gap,
        [
            {
                "source_claim_id": "claim:gap",
                "paper_id": "paper:gap",
                "target_id": "task:response_inhibition",
                "target_type": "Task",
                "claim_text": "Levodopa improves response inhibition",
                "polarity": "supports",
                "canonical_claim_id": module._canonical_claim_id(
                    target_id="task:response_inhibition",
                    target_type="Task",
                    claim_text="Levodopa improves response inhibition",
                    polarity="supports",
                ),
            }
        ],
    )
    _write_jsonl(
        accepted,
        [
            {
                "paper": {"id": "paper:new1", "title": "Posterior lateral frontal cortex paper"},
                "target": {
                    "id": "region:posterior_lateral_frontal_cortex",
                    "type": "Region",
                    "label": "posterior lateral frontal cortex",
                },
                "mapping": {"mapping_confidence": 0.9},
                "claim": {
                    "id": "claim:new1",
                    "text": "The posterior motor/premotor region of the lateral frontal cortex is functionally organized along a rostro-caudal axis.",
                    "polarity": "supports",
                },
                "evidence": {"section": "abstract", "locatable": True},
                "signals": {"title_only_evidence": False},
                "regeneration_source": {
                    "source_review_bucket": "salvage_task_or_region",
                    "source_bucket_reason": "specific_task_or_region_target",
                },
            },
            {
                "paper": {"id": "paper:new2", "title": "Motor imagery paper"},
                "target": {
                    "id": "task:motor_imagery",
                    "type": "Task",
                    "label": "motor imagery",
                },
                "mapping": {"mapping_confidence": 1.0},
                "claim": {
                    "id": "claim:new2",
                    "text": "Increased blood oxygenation level-dependent signals were observed bilaterally in the premotor areas and supplementary motor area during performance of motor imagery tasks.",
                    "polarity": "supports",
                },
                "evidence": {"section": "abstract", "locatable": True},
                "signals": {"title_only_evidence": False},
                "regeneration_source": {
                    "source_review_bucket": "salvage_task_or_region",
                    "source_bucket_reason": "specific_task_or_region_target",
                },
            },
            {
                "paper": {"id": "paper:dup", "title": "dup"},
                "target": {
                    "id": "concept:working_memory",
                    "type": "Concept",
                    "label": "working memory",
                },
                "mapping": {"mapping_confidence": 1.0},
                "claim": {
                    "id": "claim:dup",
                    "text": "Working memory load robustly recruits dlPFC.",
                    "polarity": "supports",
                },
                "evidence": {"section": "abstract", "locatable": True},
                "signals": {"title_only_evidence": False},
                "regeneration_source": {},
            },
        ],
    )

    exit_code = module.main(
        [
            "--snapshot-v2",
            str(snapshot_v2),
            "--warning-conflict-gap-pack",
            str(warning_gap),
            "--accepted-regeneration-jsonl",
            str(accepted),
            "--min-new-families",
            "2",
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "claim_snapshot_substantive_breadth_pack_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"]["base_families_total"] == 2
    assert summary["counts"]["bridge_families_total"] == 1
    assert summary["counts"]["candidate_rows_total"] == 2
    assert summary["counts"]["candidate_new_families_total"] == 2
    assert summary["counts"]["reserve_rows_total"] == 1
    assert summary["counts"]["projected_post_gap_families_total"] == 4
    assert summary["counts"]["remaining_shortfall_after_pack"] == 20
    assert summary["counts"]["candidate_target_type_Region"] == 1
    assert summary["counts"]["candidate_target_type_Task"] == 1


def test_build_claim_snapshot_substantive_breadth_pack_fails_when_minimum_not_met(
    tmp_path: Path,
) -> None:
    snapshot_v2 = tmp_path / "claim_snapshot_v2.jsonl"
    warning_gap = tmp_path / "warning_conflict_gap_pack.jsonl"
    accepted = tmp_path / "accepted_records.jsonl"
    output_dir = tmp_path / "out"

    _write_jsonl(snapshot_v2, [])
    _write_jsonl(warning_gap, [])
    _write_jsonl(
        accepted,
        [
            {
                "paper": {"id": "paper:new1", "title": "Posterior lateral frontal cortex paper"},
                "target": {
                    "id": "region:posterior_lateral_frontal_cortex",
                    "type": "Region",
                    "label": "posterior lateral frontal cortex",
                },
                "mapping": {"mapping_confidence": 0.9},
                "claim": {
                    "id": "claim:new1",
                    "text": "The posterior motor/premotor region of the lateral frontal cortex is functionally organized along a rostro-caudal axis.",
                    "polarity": "supports",
                },
                "evidence": {"section": "abstract", "locatable": True},
                "signals": {"title_only_evidence": False},
                "regeneration_source": {},
            }
        ],
    )

    try:
        module.main(
            [
                "--snapshot-v2",
                str(snapshot_v2),
                "--warning-conflict-gap-pack",
                str(warning_gap),
                "--accepted-regeneration-jsonl",
                str(accepted),
                "--min-new-families",
                "2",
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "below requested minimum" in str(exc)
    else:
        raise AssertionError("Expected breadth pack minimum failure")
