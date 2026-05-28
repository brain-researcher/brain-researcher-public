from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import (
    build_task_panel_missing_claim_resolution_pack as missing_claim_pack,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_missing_claim_resolution_pack_creates_replay_subset(
    tmp_path: Path,
) -> None:
    source_manifest = tmp_path / "source" / "manifest_task_panel.json"
    dropped_records = tmp_path / "dropped_task_panel_records.jsonl"
    missing_claim_rows = tmp_path / "skipped_missing_claim.jsonl"
    output_dir = tmp_path / "missing_claim_resolution"

    _write_json(
        source_manifest,
        {
            "run_id": "task-panel-v4",
            "source": "kggen_onvoc_postprocess",
            "query": "task-panel",
            "options": {"task_fold_mode": "subfamily"},
            "source_details": {"source_package": "v4"},
        },
    )
    _write_jsonl(
        dropped_records,
        [
            {
                "paper": {"id": "pmid:1", "title": "Emotion paper"},
                "claim": {"id": "claim:1"},
                "run": {"run_id": "run:1"},
                "target": {
                    "id": "task:onvoc:onvoc_0000463",
                    "label": "Reward Responsiveness",
                },
                "mapping": {"original_canonical_id": "concept:emotion"},
            },
            {
                "paper": {"id": "pmid:2", "title": "Gaze paper"},
                "claim": {"id": "claim:2"},
                "run": {"run_id": "run:2"},
                "target": {
                    "id": "task:subfamily:sf_social_perception_attention",
                    "label": "Social Perception",
                },
                "mapping": {"original_canonical_id": "concept:gaze_processing"},
            },
            {
                "paper": {"id": "pmid:3", "title": "Phonology paper"},
                "claim": {"id": "claim:3"},
                "run": {"run_id": "run:3"},
                "target": {
                    "id": "task:subfamily:sf_phonology_morphology",
                    "label": "Phonological Processing",
                },
                "mapping": {"original_canonical_id": "concept:phonologic_processing"},
            },
        ],
    )
    _write_jsonl(
        missing_claim_rows,
        [
            {
                "claim_id": "claim:1",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "old_task_id": "task:onvoc:onvoc_0000463",
            },
            {
                "claim_id": "claim:2",
                "paper_id": "pmid:2",
                "run_id": "run:2",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
            },
            {
                "claim_id": "claim:3",
                "paper_id": "pmid:3",
                "run_id": "run:3",
                "old_task_id": "task:subfamily:sf_phonology_morphology",
            },
        ],
    )

    assert (
        missing_claim_pack.main(
            [
                "--source-manifest",
                str(source_manifest),
                "--dropped-records",
                str(dropped_records),
                "--missing-claim-rows",
                str(missing_claim_rows),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    summary = json.loads(
        (output_dir / "missing_claim_resolution_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"] == {
        "missing_claim_rows": 3,
        "resolved_missing_claim_rows": 3,
        "unresolved_missing_claim_rows": 0,
        "expected_absent_no_replay": 1,
        "replay_candidate": 2,
        "manual_review": 0,
        "replay_candidate_publications": 2,
    }

    replay_manifest = json.loads(
        (output_dir / "replay_subset" / "manifest_task_panel.json").read_text(
            encoding="utf-8"
        )
    )
    assert replay_manifest["counts"]["records_generated"] == 2

    replay_records = [
        json.loads(line)
        for line in (output_dir / "replay_subset" / "task_panel_records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [row["claim"]["id"] for row in replay_records] == ["claim:2", "claim:3"]


def test_build_task_panel_missing_claim_resolution_pack_surfaces_unresolved_join_rows(
    tmp_path: Path,
) -> None:
    source_manifest = tmp_path / "source" / "manifest_task_panel.json"
    dropped_records = tmp_path / "dropped_task_panel_records.jsonl"
    missing_claim_rows = tmp_path / "skipped_missing_claim.jsonl"
    output_dir = tmp_path / "missing_claim_resolution"

    _write_json(
        source_manifest,
        {
            "run_id": "task-panel-v4",
            "source": "kggen_onvoc_postprocess",
            "query": "task-panel",
            "options": {"task_fold_mode": "subfamily"},
            "source_details": {"source_package": "v4"},
        },
    )
    _write_jsonl(
        dropped_records,
        [
            {
                "paper": {"id": "pmid:1", "title": "Matched paper"},
                "claim": {"id": "claim:1"},
                "run": {"run_id": "run:1"},
                "target": {
                    "id": "task:subfamily:sf_social_perception_attention",
                    "label": "Social Perception",
                },
                "mapping": {"original_canonical_id": "concept:gaze_processing"},
            }
        ],
    )
    _write_jsonl(
        missing_claim_rows,
        [
            {
                "claim_id": "claim:1",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
            },
            {
                "claim_id": "claim:missing-join",
                "paper_id": "pmid:404",
                "run_id": "run:404",
                "old_task_id": "task:subfamily:sf_sentence_syntax",
            },
        ],
    )

    assert (
        missing_claim_pack.main(
            [
                "--source-manifest",
                str(source_manifest),
                "--dropped-records",
                str(dropped_records),
                "--missing-claim-rows",
                str(missing_claim_rows),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    summary = json.loads(
        (output_dir / "missing_claim_resolution_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["counts"] == {
        "missing_claim_rows": 2,
        "resolved_missing_claim_rows": 1,
        "unresolved_missing_claim_rows": 1,
        "expected_absent_no_replay": 0,
        "replay_candidate": 1,
        "manual_review": 0,
        "replay_candidate_publications": 1,
    }
    unresolved_rows = [
        json.loads(line)
        for line in (output_dir / "unresolved_missing_claim_row.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert unresolved_rows == [
        {
            "claim_id": "claim:missing-join",
            "paper_id": "pmid:404",
            "run_id": "run:404",
            "old_task_id": "task:subfamily:sf_sentence_syntax",
            "old_task_label": "",
            "mapping_original": "",
            "paper_title": "",
            "resolution": "unresolved_missing_claim_row",
            "resolution_reason": "missing_dropped_record_join",
            "resolution_note": (
                "Missing-claim row did not join back to dropped_records; "
                "manual inspection is required before replay or closure."
            ),
        }
    ]
