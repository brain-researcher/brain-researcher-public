from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_task_panel_transition_review_pack import main


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_transition_review_pack_filters_transition(
    tmp_path: Path, monkeypatch
) -> None:
    input_jsonl = tmp_path / "review_semantic_coarsening.jsonl"
    output_dir = tmp_path / "transition_pack"
    _write_jsonl(
        input_jsonl,
        [
            {
                "paper_id": "pmid:1",
                "claim_id": "claim:1",
                "run_id": "run:1",
                "old_task_id": "task:subfamily:sf_affect_induction",
                "current_target_id": "neurostore_task:emo",
                "mapping_original": "concept:emotional_regulation",
                "paper_title": "Emotion paper",
                "onvoc_label": "Emotion Regulation",
                "current_target_label": "Emotion Regulation",
            },
            {
                "paper_id": "pmid:2",
                "claim_id": "claim:2",
                "run_id": "run:2",
                "old_task_id": "task:subfamily:sf_item_recognition",
                "current_target_id": "neurostore_task:epi",
                "mapping_original": "concept:episodic_memories",
                "paper_title": "Memory paper",
                "onvoc_label": "Episodic Memory",
                "current_target_label": "Episodic Memory",
            },
        ],
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_task_panel_transition_review_pack.py",
            "--input-jsonl",
            str(input_jsonl),
            "--old-task-id",
            "task:subfamily:sf_affect_induction",
            "--current-target-id",
            "neurostore_task:emo",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert main() == 0

    summary = json.loads(
        (output_dir / "transition_review_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"] == {"transition_rows": 1}
    assert summary["counts_by_mapping_original"] == [
        ["concept:emotional_regulation", 1]
    ]
