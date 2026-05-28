from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_claim_snapshot_v1_expansion_pack as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_claim_snapshot_v1_expansion_pack_filters_reviewed_rows_and_reports_progress(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "claim_snapshot_v1.jsonl"
    prior = tmp_path / "claim_clustering_adjudication_pack.jsonl"
    calibration = tmp_path / "calibration.jsonl"
    heldout = tmp_path / "heldout.jsonl"
    accepted_regen = tmp_path / "accepted_records.jsonl"
    output_dir = tmp_path / "out"

    snapshot_row = {
        "source_claim_id": "claim:wm_dlpfc",
        "paper_id": "pmid:1",
        "target_id": "concept:working_memory",
        "target_type": "Concept",
        "claim_text": "Working memory load robustly recruits dlPFC.",
        "claim_kind": "claim",
        "polarity": "supports",
        "quality_profile": "high_precision",
        "benchmark_eligibility": "benchmark_eligible_high_precision",
        "candidate_lane_present": False,
        "canonical_claim_id": module._canonical_claim_id(
            target_id="concept:working_memory",
            target_type="Concept",
            claim_text="Working memory load robustly recruits dlPFC.",
            polarity="supports",
        ),
        "cluster_confidence": 0.95,
        "failure_tags": [],
        "snapshot_role": "control",
    }
    _write_jsonl(snapshot, [snapshot_row])
    _write_jsonl(
        prior,
        [
            {
                **snapshot_row,
                "snapshot_v1_included": True,
            },
            {
                "source_claim_id": "claim:old_excluded",
                "paper_id": "pmid:old",
                "target_id": "concept:old",
                "target_type": "Concept",
                "claim_text": "Old excluded concept row.",
                "claim_kind": "claim",
                "polarity": "supports",
                "quality_profile": "kg_bootstrap",
                "benchmark_eligibility": "bootstrap_only_pre_gate_b",
                "candidate_lane_present": False,
                "canonical_claim_id": module._canonical_claim_id(
                    target_id="concept:old",
                    target_type="Concept",
                    claim_text="Old excluded concept row.",
                    polarity="supports",
                ),
                "cluster_confidence": 0.2,
                "failure_tags": ["title_only_or_insufficient_text"],
                "snapshot_v1_included": False,
            },
        ],
    )
    _write_jsonl(
        calibration,
        [
            {
                "hypothesis_id": "claim:wm_dlpfc",
                "text": "Working memory load robustly recruits dlPFC.",
                "review_status": "accepted_high_precision",
                "source_records": [
                    {
                        "paper_id": "pmid:1",
                        "target_id": "concept:working_memory",
                        "target_type": "Concept",
                        "claim_id": "claim:wm_dlpfc",
                        "polarity": "supports",
                        "gate_profile": "high_precision",
                        "review_status": "accepted_high_precision",
                    },
                    {
                        "paper_id": "pmid:2",
                        "target_id": "task:response_inhibition",
                        "target_type": "Task",
                        "claim_id": "claim:ri_new",
                        "polarity": "supports",
                        "gate_profile": "kg_bootstrap",
                        "review_status": "accepted_bootstrap",
                    },
                ],
            }
        ],
    )
    _write_jsonl(
        heldout,
        [
            {
                "hypothesis_id": "claim:wm_dlpfc_dup",
                "text": "Working memory load robustly recruits dlPFC.",
                "review_status": "accepted_bootstrap",
                "source_records": [
                    {
                        "paper_id": "pmid:3",
                        "target_id": "concept:working_memory",
                        "target_type": "Concept",
                        "claim_id": "claim:wm_new_member",
                        "polarity": "supports",
                        "gate_profile": "kg_bootstrap",
                        "review_status": "accepted_bootstrap",
                    }
                ],
            }
        ],
    )
    _write_jsonl(
        accepted_regen,
        [
            {
                "paper": {"id": "paper:10.test/region", "title": "Region paper"},
                "target": {
                    "id": "region:caudate",
                    "type": "Region",
                    "label": "Caudate",
                },
                "mapping": {"mapping_confidence": 0.95},
                "claim": {
                    "id": "claim:region_new",
                    "text": "Caudate activation increased during reward anticipation.",
                    "polarity": "supports",
                },
                "evidence": {"section": "abstract", "locatable": True},
                "signals": {"title_only_evidence": False, "section_level_evidence": True},
                "regeneration_source": {
                    "source_review_bucket": "salvage_task_or_region",
                    "source_bucket_reason": "specific_task_or_region_target",
                },
            },
            {
                "paper": {"id": "paper:10.test/skip", "title": "Skip me"},
                "target": {
                    "id": "concept:skip",
                    "type": "Concept",
                    "label": "Skip",
                },
                "mapping": {"mapping_confidence": 0.95},
                "claim": {
                    "id": "claim:skip_title_only",
                    "text": "Skip title only row.",
                    "polarity": "supports",
                },
                "evidence": {"section": "title", "locatable": True},
                "signals": {"title_only_evidence": True, "section_level_evidence": False},
                "regeneration_source": {},
            },
        ],
    )

    exit_code = module.main(
        [
            "--snapshot-v1",
            str(snapshot),
            "--prior-adjudication-pack",
            str(prior),
            "--calibration-manifest",
            str(calibration),
            "--heldout-manifest",
            str(heldout),
            "--accepted-regeneration-jsonl",
            str(accepted_regen),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    summary = json.loads(
        (output_dir / "claim_snapshot_v1_expansion_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["current_reviewed_families_total"] == 1
    assert summary["counts"]["candidate_rows_total"] == 3
    assert summary["counts"]["candidate_canonical_families_total"] == 3
    assert summary["counts"]["candidate_new_families_total"] == 2
    assert summary["counts"]["candidate_expands_existing_families_total"] == 1
    assert summary["counts"]["candidate_warning_or_conflict_families_total"] == 2
    assert summary["counts"]["skipped_prior_reviewed_rows_total"] == 1
    assert summary["counts"]["projected_canonical_families_total"] == 3
    assert summary["counts"]["projected_warning_or_conflict_families_total"] == 2
    assert summary["counts"]["projected_target_type_buckets_total"] == 3
    assert summary["counts"]["threshold_target_type_buckets_met"] is True
    assert summary["counts"]["threshold_all_met"] is False

    rows = [
        json.loads(line)
        for line in (output_dir / "claim_snapshot_v1_expansion_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    row_by_claim = {row["source_claim_id"]: row for row in rows}
    assert set(row_by_claim) == {
        "claim:ri_new",
        "claim:wm_new_member",
        "claim:region_new",
    }
    assert row_by_claim["claim:ri_new"]["family_is_new_to_snapshot_v1"] is True
    assert row_by_claim["claim:ri_new"]["family_has_warning_or_conflict"] is True
    assert row_by_claim["claim:wm_new_member"]["family_is_new_to_snapshot_v1"] is False
    assert row_by_claim["claim:wm_new_member"]["expands_existing_snapshot_family"] is True
    assert row_by_claim["claim:wm_new_member"]["family_has_warning_or_conflict"] is True
    assert row_by_claim["claim:region_new"]["target_type"] == "Region"
    assert row_by_claim["claim:region_new"]["expansion_seed_bucket"] == "accepted_regeneration_seed"


def test_build_claim_snapshot_v1_expansion_pack_fails_closed_on_reviewed_drift(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "claim_snapshot_v1.jsonl"
    prior = tmp_path / "claim_clustering_adjudication_pack.jsonl"
    calibration = tmp_path / "calibration.jsonl"
    heldout = tmp_path / "heldout.jsonl"
    accepted_regen = tmp_path / "accepted_records.jsonl"
    output_dir = tmp_path / "out"

    reviewed_row = {
        "source_claim_id": "claim:reviewed",
        "paper_id": "pmid:1",
        "target_id": "concept:working_memory",
        "target_type": "Concept",
        "claim_text": "Working memory load robustly recruits dlPFC.",
        "claim_kind": "claim",
        "polarity": "supports",
        "quality_profile": "high_precision",
        "benchmark_eligibility": "benchmark_eligible_high_precision",
        "candidate_lane_present": False,
        "canonical_claim_id": module._canonical_claim_id(
            target_id="concept:working_memory",
            target_type="Concept",
            claim_text="Working memory load robustly recruits dlPFC.",
            polarity="supports",
        ),
        "cluster_confidence": 0.95,
        "failure_tags": [],
        "snapshot_role": "control",
    }
    _write_jsonl(snapshot, [{**reviewed_row}])
    _write_jsonl(prior, [{**reviewed_row, "snapshot_v1_included": True}])
    _write_jsonl(
        calibration,
        [
            {
                "hypothesis_id": "claim:reviewed",
                "text": "Working memory load robustly recruits dlPFC.",
                "review_status": "accepted_high_precision",
                "source_records": [
                    {
                        "paper_id": "pmid:1",
                        "target_id": "concept:changed_target",
                        "target_type": "Concept",
                        "claim_id": "claim:reviewed",
                        "polarity": "supports",
                        "gate_profile": "high_precision",
                        "review_status": "accepted_high_precision",
                    }
                ],
            }
        ],
    )
    _write_jsonl(heldout, [])
    _write_jsonl(accepted_regen, [])

    try:
        module.main(
            [
                "--snapshot-v1",
                str(snapshot),
                "--prior-adjudication-pack",
                str(prior),
                "--calibration-manifest",
                str(calibration),
                "--heldout-manifest",
                str(heldout),
                "--accepted-regeneration-jsonl",
                str(accepted_regen),
                "--output-dir",
                str(output_dir),
            ]
        )
    except SystemExit as exc:
        assert "Fail-closed reviewed drift" in str(exc)
    else:
        raise AssertionError("Expected reviewed drift failure")
