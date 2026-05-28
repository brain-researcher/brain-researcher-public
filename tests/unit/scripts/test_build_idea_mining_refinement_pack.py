from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_idea_mining_refinement_pack as module


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_idea_mining_refinement_pack_buckets_and_dedupes(tmp_path: Path) -> None:
    review_rows = tmp_path / "review_rows.jsonl"
    output_dir = tmp_path / "out"
    _write_jsonl(
        review_rows,
        [
            {
                "candidate_card_id": "card:search",
                "seed_id": "concept:attention",
                "title": "Task bridge",
                "hypothesis": "Task bridge hypothesis",
                "candidate_kg_id": "neurostore_task:abc",
                "relation_hint": "SEARCH_EXPANDED",
                "run_spec_id": "search_broad",
                "candidate_lane_mode": "broad",
                "verdict": "insufficient_evidence",
                "raw_total": 14,
                "failure_tags": ["insufficient_evidence_verdict"],
                "paired_broad_strict_delta": False,
            },
            {
                "candidate_card_id": "card:search",
                "seed_id": "concept:attention",
                "title": "Task bridge",
                "hypothesis": "Task bridge hypothesis",
                "candidate_kg_id": "neurostore_task:abc",
                "relation_hint": "SEARCH_EXPANDED",
                "run_spec_id": "search_strict",
                "candidate_lane_mode": "strict",
                "verdict": "insufficient_evidence",
                "raw_total": 13,
                "failure_tags": ["insufficient_evidence_verdict"],
                "paired_broad_strict_delta": False,
            },
            {
                "candidate_card_id": "card:dataset",
                "seed_id": "ds:openneuro:ds000114",
                "title": "4:anon node",
                "hypothesis": "Dataset bridge hypothesis",
                "candidate_kg_id": "4:anon",
                "relation_hint": "",
                "run_spec_id": "dataset_broad",
                "candidate_lane_mode": "broad",
                "verdict": "insufficient_evidence",
                "raw_total": 13,
                "failure_tags": ["insufficient_evidence_verdict"],
                "paired_broad_strict_delta": False,
                "pair_summary": {"has_pair": True},
            },
        ],
    )

    exit_code = module.main(
        [
            "--review-rows-jsonl",
            str(review_rows),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    pack_rows = [
        json.loads(line)
        for line in (output_dir / "idea_mining_refinement_pack_v1.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(pack_rows) == 2
    assert pack_rows[0]["refinement_bucket"] == "search_expanded_bridge"
    assert pack_rows[1]["refinement_bucket"] == "dataset_seed_entity_leakage"
    assert pack_rows[1]["recommended_action"] == "drop_from_candidate_sensitive_pack"

    summary = json.loads(
        (output_dir / "idea_mining_refinement_pack_v1_summary.json").read_text(encoding="utf-8")
    )
    assert summary["rows_total"] == 2
    assert summary["drop_from_candidate_sensitive_pack_total"] == 1


def test_build_idea_mining_refinement_pack_detects_mapping_bridge(tmp_path: Path) -> None:
    pack_rows, summary = module.build_refinement_pack(
        [
            {
                "candidate_card_id": "card:mapping",
                "seed_id": "task:seed",
                "title": "Memory",
                "hypothesis": "Memory bridge hypothesis",
                "candidate_kg_id": "4:anon-memory",
                "relation_hint": "MAPS_TO",
                "run_spec_id": "mapping",
                "candidate_lane_mode": "broad",
                "verdict": "insufficient_evidence",
                "raw_total": 13,
                "failure_tags": ["insufficient_evidence_verdict"],
                "paired_broad_strict_delta": False,
                "pair_summary": {"has_pair": True},
            }
        ]
    )
    assert pack_rows[0]["refinement_bucket"] == "mapping_bridge"
    assert summary["bucket_counts"]["mapping_bridge"] == 1


def test_build_idea_mining_refinement_pack_detects_pair_incomplete_replay(tmp_path: Path) -> None:
    pack_rows, summary = module.build_refinement_pack(
        [
            {
                "candidate_card_id": "card:incomplete",
                "seed_id": "task:seed",
                "title": "Selective & Spatial Attention OOD hypothesis",
                "hypothesis": "Task family bridge hypothesis",
                "candidate_kg_id": "4:anon-family",
                "relation_hint": "BELONGS_TO_FAMILY",
                "run_spec_id": "family_strict_only",
                "candidate_lane_mode": "strict",
                "verdict": "insufficient_evidence",
                "raw_total": 13,
                "failure_tags": ["insufficient_evidence_verdict"],
                "paired_broad_strict_delta": False,
                "pair_summary": {"has_pair": False},
            }
        ]
    )
    assert pack_rows[0]["refinement_bucket"] == "pair_incomplete_replay"
    assert pack_rows[0]["recommended_action"] == "rerun_missing_lane_before_refinement"
    assert summary["bucket_counts"]["pair_incomplete_replay"] == 1
