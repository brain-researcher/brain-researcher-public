from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_task_panel_cleanup_candidates as cleanup_candidates


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


def test_build_task_panel_cleanup_candidates_respects_protection_and_live_state(
    tmp_path: Path, monkeypatch
) -> None:
    dropped_records = tmp_path / "dropped_task_panel_records.jsonl"
    protected_claim_ids = tmp_path / "protected_claim_ids.txt"
    keep_exception_claim_ids = tmp_path / "keep_exception_claim_ids.txt"
    output_dir = tmp_path / "cleanup_candidates"

    _write_jsonl(
        dropped_records,
        [
            {
                "paper": {"id": "pmid:1", "title": "Protected paper"},
                "claim": {"id": "claim:protected"},
                "run": {"run_id": "run:1"},
                "target": {
                    "id": "task:onvoc:onvoc_0000466",
                    "label": "Social Perception",
                    "onvoc_id": "ONVOC_0000466",
                },
                "mapping": {"original_canonical_id": "concept:social_perception"},
            },
            {
                "paper": {"id": "pmid:2", "title": "Cleanup paper"},
                "claim": {"id": "claim:cleanup"},
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
            },
            {
                "paper": {"id": "pmid:3", "title": "Drifted paper"},
                "claim": {"id": "claim:drift"},
                "run": {"run_id": "run:3"},
                "target": {
                    "id": "task:onvoc:onvoc_0000428",
                    "label": "Risk Ambiguity",
                    "onvoc_id": "ONVOC_0000428",
                },
                "mapping": {
                    "original_canonical_id": "concept:risk_ambiguity",
                    "onvoc_id": "ONVOC_0000428",
                },
            },
            {
                "paper": {"id": "pmid:4", "title": "Missing claim paper"},
                "claim": {"id": "claim:missing"},
                "run": {"run_id": "run:4"},
                "target": {
                    "id": "task:onvoc:onvoc_0000462",
                    "label": "Emotion Regulation",
                    "onvoc_id": "ONVOC_0000462",
                },
                "mapping": {
                    "original_canonical_id": "concept:emotion_regulation",
                    "onvoc_id": "ONVOC_0000462",
                },
            },
            {
                "paper": {"id": "pmid:5", "title": "Keep-exception paper"},
                "claim": {"id": "claim:drift-protected"},
                "run": {"run_id": "run:5"},
                "target": {
                    "id": "task:subfamily:sf_item_recognition",
                    "label": "Item Recognition",
                    "onvoc_id": "ONVOC_0000485",
                },
                "mapping": {
                    "original_canonical_id": "concept:episodic_memories",
                    "onvoc_id": "ONVOC_0000485",
                },
            },
        ],
    )
    protected_claim_ids.write_text("claim:protected\n", encoding="utf-8")
    keep_exception_claim_ids.write_text("claim:drift-protected\n", encoding="utf-8")

    states = {
        ("claim:cleanup", "pmid:2", "run:2"): {
            "claim_id": "claim:cleanup",
            "current_target_id": "task:onvoc:onvoc_0000478",
            "claim_paper_id": "pmid:2",
            "publication_id": "pmid:2",
            "run_mention_task_ids": ["task:onvoc:onvoc_0000478"],
            "missing_mentions": False,
            "missing_publication": False,
        },
        ("claim:drift", "pmid:3", "run:3"): {
            "claim_id": "claim:drift",
            "current_target_id": "neurostore_task:SL5Qq3YkFSAD:fmri:0",
            "claim_paper_id": "pmid:3",
            "publication_id": "pmid:3",
            "run_mention_task_ids": ["neurostore_task:SL5Qq3YkFSAD:fmri:0"],
            "missing_mentions": False,
            "missing_publication": False,
        },
        ("claim:missing", "pmid:4", "run:4"): None,
        ("claim:drift-protected", "pmid:5", "run:5"): {
            "claim_id": "claim:drift-protected",
            "current_target_id": "neurostore_task:2oMh3nFe82q8:fmri:0",
            "claim_paper_id": "pmid:5",
            "publication_id": "pmid:5",
            "run_mention_task_ids": ["neurostore_task:2oMh3nFe82q8:fmri:0"],
            "missing_mentions": False,
            "missing_publication": False,
        },
    }

    monkeypatch.setattr(
        cleanup_candidates.GraphDatabase,
        "driver",
        lambda *args, **kwargs: _FakeDriver(states),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_task_panel_cleanup_candidates.py",
            "--dropped-records",
            str(dropped_records),
            "--protected-claim-ids",
            str(protected_claim_ids),
            "--protected-claim-ids",
            str(keep_exception_claim_ids),
            "--output-dir",
            str(output_dir),
            "--neo4j-password",
            "test-password",
        ],
    )

    assert cleanup_candidates.main() == 0

    summary = json.loads(
        (output_dir / "cleanup_candidate_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"] == {
        "candidate_rows": 5,
        "cleanup_candidates": 1,
        "needs_cleanup": 1,
        "skipped_protected": 2,
        "skipped_target_drift": 1,
        "skipped_missing_claim": 1,
        "missing_publication": 0,
        "missing_mentions": 0,
        "protected_claim_ids_loaded": 2,
    }
    assert summary["protected_claim_ids_paths"] == [
        str(protected_claim_ids.resolve()),
        str(keep_exception_claim_ids.resolve()),
    ]

    cleanup_rows = [
        json.loads(line)
        for line in (output_dir / "cleanup_candidates.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(cleanup_rows) == 1
    assert cleanup_rows[0]["claim_id"] == "claim:cleanup"
    assert cleanup_rows[0]["old_task_id"] == "task:onvoc:onvoc_0000478"
    assert cleanup_rows[0]["current_target_id"] == "task:onvoc:onvoc_0000478"

    protected_rows = [
        json.loads(line)
        for line in (output_dir / "skipped_protected.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert protected_rows == [
        {
            "claim_id": "claim:protected",
            "paper_id": "pmid:1",
            "run_id": "run:1",
            "old_task_id": "task:onvoc:onvoc_0000466",
        },
        {
            "claim_id": "claim:drift-protected",
            "paper_id": "pmid:5",
            "run_id": "run:5",
            "old_task_id": "task:subfamily:sf_item_recognition",
        },
    ]

    drift_rows = [
        json.loads(line)
        for line in (output_dir / "skipped_target_drift.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert drift_rows == [
        {
            "claim_id": "claim:drift",
            "paper_id": "pmid:3",
            "run_id": "run:3",
            "old_task_id": "task:onvoc:onvoc_0000428",
            "current_target_id": "neurostore_task:SL5Qq3YkFSAD:fmri:0",
        }
    ]

    missing_rows = [
        json.loads(line)
        for line in (output_dir / "skipped_missing_claim.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert missing_rows == [
        {
            "claim_id": "claim:missing",
            "paper_id": "pmid:4",
            "run_id": "run:4",
            "old_task_id": "task:onvoc:onvoc_0000462",
        }
    ]
