from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import (
    build_social_perception_replay_review_pack as social_review,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_social_perception_replay_review_pack_buckets_rows(tmp_path: Path) -> None:
    replay_candidates = tmp_path / "replay_candidate.jsonl"
    output_dir = tmp_path / "social_review"

    _write_jsonl(
        replay_candidates,
        [
            {
                "claim_id": "claim:1",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
                "mapping_original": "concept:gaze_processing",
                "paper_title": "Gaze paper",
            },
            {
                "claim_id": "claim:2",
                "paper_id": "pmid:2",
                "run_id": "run:2",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
                "mapping_original": "concept:valence_processing",
                "paper_title": "Valence paper",
            },
            {
                "claim_id": "claim:3",
                "paper_id": "pmid:3",
                "run_id": "run:3",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
                "mapping_original": "concept:cue_processing",
                "paper_title": "Cue paper",
            },
            {
                "claim_id": "claim:4",
                "paper_id": "pmid:4",
                "run_id": "run:4",
                "old_task_id": "task:subfamily:sf_phonology_morphology",
                "mapping_original": "concept:phonologic_processing",
                "paper_title": "Phonology paper",
            },
        ],
    )

    assert (
        social_review.main(
            [
                "--replay-candidates",
                str(replay_candidates),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    summary = json.loads(
        (output_dir / "social_perception_replay_review_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"] == {
        "review_rows": 3,
        "face_gaze_social_core": 1,
        "affect_valence_social_boundary": 1,
        "cue_reactivity_non_social": 1,
        "language_pragmatics_non_social": 0,
        "generic_cognitive_sensory_non_social": 0,
        "meta_review_noise": 0,
        "unexpected_social_replay_row": 0,
    }
