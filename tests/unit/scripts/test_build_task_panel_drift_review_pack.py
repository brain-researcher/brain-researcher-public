from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_task_panel_drift_review_pack as drift_pack


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class _FakeSession:
    def __init__(self, states: dict[tuple[str, str, str], dict | None]) -> None:
        self._states = states

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute_read(self, func, **kwargs):
        del func
        return self._states.get(
            (kwargs["claim_id"], kwargs["paper_id"], kwargs["run_id"])
        )


class _FakeDriver:
    def __init__(self, states: dict[tuple[str, str, str], dict | None]) -> None:
        self._states = states

    def __enter__(self) -> _FakeDriver:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def session(self, database=None):
        del database
        return _FakeSession(self._states)


def test_build_task_panel_drift_review_pack_outputs_bounded_drift_rows(
    tmp_path: Path, monkeypatch
) -> None:
    dropped_records = tmp_path / "dropped_task_panel_records.jsonl"
    cleanup_report = tmp_path / "cleanup_report.json"
    current_records = tmp_path / "v8" / "task_panel_records.jsonl"
    output_dir = tmp_path / "review_pack"

    _write_json(
        cleanup_report,
        {
            "candidate_rows": 3,
            "skipped_target_drift": 1,
            "needs_cleanup": 1,
            "skipped_missing_claim": 1,
        },
    )
    _write_jsonl(
        dropped_records,
        [
            {
                "paper": {"id": "pmid:1", "title": "Attention paper"},
                "claim": {"id": "claim:1"},
                "run": {"run_id": "run:1"},
                "target": {
                    "id": "task:onvoc:onvoc_0000466",
                    "label": "Cognitive Inhibition",
                    "onvoc_id": "ONVOC_0000466",
                },
                "mapping": {
                    "original_canonical_id": "concept:attention",
                    "onvoc_id": "ONVOC_0000466",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_0000466",
                        "onvoc_label": "Cognitive Inhibition",
                    },
                    "task_panel": {"router_reason": "router_generic_construct"},
                },
            },
            {
                "paper": {"id": "pmid:2", "title": "Reading paper"},
                "claim": {"id": "claim:2"},
                "run": {"run_id": "run:2"},
                "target": {
                    "id": "task:onvoc:onvoc_0000478",
                    "label": "Reading Comprehension",
                    "onvoc_id": "ONVOC_0000478",
                },
                "mapping": {
                    "original_canonical_id": "concept:word_reading",
                    "onvoc_id": "ONVOC_0000478",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_0000478",
                        "onvoc_label": "Reading Comprehension",
                    }
                },
            },
            {
                "paper": {"id": "pmid:3", "title": "Missing claim paper"},
                "claim": {"id": "claim:3"},
                "run": {"run_id": "run:3"},
                "target": {
                    "id": "task:onvoc:onvoc_0000462",
                    "label": "Emotion Regulation",
                    "onvoc_id": "ONVOC_0000462",
                },
                "mapping": {
                    "original_canonical_id": "concept:emotion_regulation",
                    "onvoc_id": "ONVOC_0000462",
                },
                "normalization": {
                    "onvoc": {
                        "onvoc_id": "ONVOC_0000462",
                        "onvoc_label": "Emotion Regulation",
                    }
                },
            },
        ],
    )
    _write_jsonl(
        current_records,
        [
            {
                "paper": {"id": "pmid:1"},
                "claim": {"id": "claim:1"},
                "run": {"run_id": "run:1"},
                "normalization": {
                    "task_panel": {
                        "router_reason": "router_review_only",
                        "router_label_type": "review_only",
                        "router_input_label": "attention",
                        "task_id": "task:subfamily:sf_selective_attention",
                    }
                },
            }
        ],
    )

    states = {
        ("claim:1", "pmid:1", "run:1"): {
            "claim_id": "claim:1",
            "current_target_id": "neurostore_task:SL5Qq3YkFSAD:fmri:0",
            "claim_paper_id": "pmid:1",
            "publication_id": "pmid:1",
            "current_target_label": "Social Perception Task",
            "current_target_onvoc_id": "",
            "current_target_family_id": "",
            "current_target_subfamily_id": "",
            "run_mention_task_ids": ["neurostore_task:SL5Qq3YkFSAD:fmri:0"],
        },
        ("claim:2", "pmid:2", "run:2"): {
            "claim_id": "claim:2",
            "current_target_id": "task:onvoc:onvoc_0000478",
            "claim_paper_id": "pmid:2",
            "publication_id": "pmid:2",
            "current_target_label": "Reading Comprehension",
            "current_target_onvoc_id": "ONVOC_0000478",
            "current_target_family_id": "",
            "current_target_subfamily_id": "",
            "run_mention_task_ids": ["task:onvoc:onvoc_0000478"],
        },
        ("claim:3", "pmid:3", "run:3"): None,
    }

    monkeypatch.setattr(
        drift_pack.GraphDatabase,
        "driver",
        lambda *args, **kwargs: _FakeDriver(states),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_task_panel_drift_review_pack.py",
            "--dropped-records",
            str(dropped_records),
            "--cleanup-report",
            str(cleanup_report),
            "--current-package-records",
            str(current_records),
            "--output-dir",
            str(output_dir),
            "--neo4j-password",
            "test-password",
        ],
    )

    assert drift_pack.main() == 0

    summary = json.loads(
        (output_dir / "drift_review_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"] == {
        "candidate_rows": 3,
        "drift_rows": 1,
        "missing_claim_rows": 1,
        "unchanged_rows": 1,
    }
    assert summary["counts_by_current_target_namespace"] == [["neurostore_task", 1]]
    assert summary["counts_by_review_bucket"] == [["1_neurostore_task", 1]]
    assert summary["counts_by_mapping_original"] == [["concept:attention", 1]]
    assert summary["top_transitions"] == [
        [
            "task:onvoc:onvoc_0000466",
            "neurostore_task:SL5Qq3YkFSAD:fmri:0",
            1,
        ]
    ]

    rows = [
        json.loads(line)
        for line in (output_dir / "drift_review_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["review_bucket"] == "1_neurostore_task"
    assert rows[0]["current_target_namespace"] == "neurostore_task"
    assert rows[0]["mapping_original"] == "concept:attention"
    assert rows[0]["v8_router_reason"] == "router_review_only"
    assert rows[0]["v8_router_input_label"] == "attention"
