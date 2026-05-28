from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_task_panel_social_reroute_pack as reroute_pack


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_social_reroute_pack_groups_cleanup_queue_rows(
    tmp_path: Path,
) -> None:
    cleanup_candidates = tmp_path / "cleanup_candidates.jsonl"
    social_review_pack = tmp_path / "social_review_pack.jsonl"
    output_dir = tmp_path / "reroute_pack"

    _write_jsonl(
        cleanup_candidates,
        [
            {
                "claim_id": "claim:1",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
                "current_target_id": "task:subfamily:sf_social_perception_attention",
                "mapping_original": "concept:cue_processing",
                "paper_title": "Cue paper",
            },
            {
                "claim_id": "claim:2",
                "paper_id": "pmid:2",
                "run_id": "run:2",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
                "current_target_id": "task:subfamily:sf_social_perception_attention",
                "mapping_original": "concept:core_processing",
                "paper_title": "Meta paper",
            },
        ],
    )
    _write_jsonl(
        social_review_pack,
        [
            {
                "claim_id": "claim:1",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "review_decision": "cue_reactivity_non_social",
                "decision_reason": "cue_salience_non_social",
                "decision_note": "cue row",
                "record": {"claim": {"id": "claim:1"}},
            },
            {
                "claim_id": "claim:2",
                "paper_id": "pmid:2",
                "run_id": "run:2",
                "review_decision": "meta_review_noise",
                "decision_reason": "meta_review_or_method_summary",
                "decision_note": "meta row",
                "record": {"claim": {"id": "claim:2"}},
            },
        ],
    )

    assert (
        reroute_pack.main(
            [
                "--cleanup-candidates",
                str(cleanup_candidates),
                "--social-review-pack",
                str(social_review_pack),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    summary = json.loads(
        (output_dir / "social_reroute_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"] == {
        "cleanup_queue_rows": 2,
        "reroute_review": 1,
        "cleanup_now": 1,
        "manual_review": 0,
        "unmatched_cleanup_rows": 0,
    }

    cleanup_now_ids = (output_dir / "cleanup_now_claim_ids.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert cleanup_now_ids == ["claim:2"]
    cleanup_now_rows = [
        json.loads(line)
        for line in (output_dir / "cleanup_now.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(cleanup_now_rows) == 1
    assert cleanup_now_rows[0]["claim_id"] == "claim:2"
    assert summary["artifacts"]["cleanup_now_jsonl"] == str(
        output_dir / "cleanup_now.jsonl"
    )

    reroute_records = [
        json.loads(line)
        for line in (output_dir / "reroute_review_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert reroute_records == [{"claim": {"id": "claim:1"}}]
    cue_lane_records = [
        json.loads(line)
        for line in (output_dir / "lane_cue_reactivity_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert cue_lane_records == [{"claim": {"id": "claim:1"}}]
