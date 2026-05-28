from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import apply_task_panel_cleanup_now as cleanup_now


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class _FakeSession:
    def __init__(self, states: dict[tuple[str, str, str, str], dict | None]) -> None:
        self._states = states

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute_read(self, func, **kwargs):
        del func
        return self._states.get(
            (
                kwargs["claim_id"],
                kwargs["paper_id"],
                kwargs["run_id"],
                kwargs["old_task_id"],
            )
        )

    def execute_write(self, func, **kwargs):
        del func
        return {
            "deleted_mentions": 1,
            "deleted_claims": 1,
            "deleted_evidence": 1,
        }


class _FakeDriver:
    def __init__(self, states: dict[tuple[str, str, str, str], dict | None]) -> None:
        self._states = states

    def __enter__(self) -> _FakeDriver:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def session(self, database=None):
        del database
        return _FakeSession(self._states)


def test_apply_task_panel_cleanup_now_dry_run_and_apply(tmp_path: Path, monkeypatch) -> None:
    cleanup_rows = tmp_path / "cleanup_now.jsonl"
    dry_run_output = tmp_path / "dryrun.json"
    apply_output = tmp_path / "apply.json"

    _write_jsonl(
        cleanup_rows,
        [
            {
                "claim_id": "claim:1",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "old_task_id": "task:subfamily:sf_social_perception_attention",
            }
        ],
    )

    states = {
        (
            "claim:1",
            "pmid:1",
            "run:1",
            "task:subfamily:sf_social_perception_attention",
        ): {
            "claim_id": "claim:1",
            "current_target_id": "task:subfamily:sf_social_perception_attention",
            "publication_id": "pmid:1",
            "mention_count": 1,
            "evidence_ids": ["evidence:1"],
        }
    }

    monkeypatch.setattr(
        cleanup_now.GraphDatabase,
        "driver",
        lambda *args, **kwargs: _FakeDriver(states),
    )

    assert (
        cleanup_now.main(
            [
                "--cleanup-rows",
                str(cleanup_rows),
                "--dry-run",
                "--output-json",
                str(dry_run_output),
                "--neo4j-password",
                "test-password",
            ]
        )
        == 0
    )
    dry_run_report = json.loads(dry_run_output.read_text(encoding="utf-8"))
    assert dry_run_report["summary"] == {
        "candidate_rows": 1,
        "needs_cleanup": 1,
        "cleaned_rows": 0,
        "skipped_missing_claim": 0,
        "skipped_target_drift": 0,
        "claims_deleted": 0,
        "evidence_deleted": 0,
        "mention_edges_deleted": 0,
    }

    assert (
        cleanup_now.main(
            [
                "--cleanup-rows",
                str(cleanup_rows),
                "--output-json",
                str(apply_output),
                "--neo4j-password",
                "test-password",
            ]
        )
        == 0
    )
    apply_report = json.loads(apply_output.read_text(encoding="utf-8"))
    assert apply_report["summary"] == {
        "candidate_rows": 1,
        "needs_cleanup": 0,
        "cleaned_rows": 1,
        "skipped_missing_claim": 0,
        "skipped_target_drift": 0,
        "claims_deleted": 1,
        "evidence_deleted": 1,
        "mention_edges_deleted": 1,
    }
