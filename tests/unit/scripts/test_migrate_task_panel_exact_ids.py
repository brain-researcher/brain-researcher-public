from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import migrate_task_panel_exact_ids as migrate_exact_ids


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class _FakeSession:
    def __init__(
        self,
        states: dict[tuple[str, str, str, str], dict | None],
        apply_results: list[dict],
    ) -> None:
        self._states = states
        self._apply_results = apply_results

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
                kwargs["new_target_id"],
            )
        )

    def execute_write(self, func, **kwargs):
        del func
        result = {
            "status": "migrated",
            "claim_id": kwargs["row"]["claim_id"],
            "paper_id": kwargs["row"]["paper_id"],
            "run_id": kwargs["row"]["run_id"],
            "new_target_id": kwargs["row"]["new_target_id"],
            "old_mentions_deleted": 1,
            "orphan_nodes_pruned": 0,
        }
        self._apply_results.append(result)
        return result


class _FakeDriver:
    def __init__(
        self,
        states: dict[tuple[str, str, str, str], dict | None],
        apply_results: list[dict],
    ) -> None:
        self._states = states
        self._apply_results = apply_results

    def __enter__(self) -> _FakeDriver:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def session(self, database=None):
        del database
        return _FakeSession(self._states, self._apply_results)


def test_migrate_task_panel_exact_ids_supports_concept_targets(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "manifest_task_panel.json"
    records_path = tmp_path / "task_panel_records.jsonl"
    dry_run_output = tmp_path / "dryrun.json"
    apply_output = tmp_path / "apply.json"

    manifest.write_text(json.dumps({"run_id": "reroute-ci"}, indent=2), encoding="utf-8")
    _write_jsonl(
        records_path,
        [
            {
                "paper": {"id": "pmid:1"},
                "run": {"run_id": "run:1"},
                "claim": {"id": "claim:1", "text": "ci processing claim"},
                "target": {
                    "type": "Concept",
                    "id": "concept:ci_processing",
                    "label": "Discourse/Pragmatics",
                    "original_id": "concept:ci_processing",
                },
                "mapping": {
                    "canonical_id": "concept:ci_processing",
                    "mapping_type": "synonym",
                    "mapping_confidence": 0.85,
                    "original_canonical_id": "concept:ci_processing",
                },
                "normalization": {},
            }
        ],
    )

    states = {
        ("claim:1", "pmid:1", "run:1", "concept:ci_processing"): {
            "claim_target_id": "task:subfamily:sf_social_perception_attention",
            "claim_paper_id": "pmid:1",
            "publication_id": "pmid:1",
            "has_new_target_link": False,
            "run_mentions": [
                {
                    "target_id": "task:subfamily:sf_social_perception_attention",
                    "target_labels": ["Task"],
                    "rel_props": {"run_id": "run:1", "mention_strength": 0.8},
                }
            ],
        }
    }
    apply_results: list[dict] = []

    monkeypatch.setattr(
        migrate_exact_ids.GraphDatabase,
        "driver",
        lambda *args, **kwargs: _FakeDriver(states, apply_results),
    )

    assert (
        migrate_exact_ids.main(
            [
                "--manifest",
                str(manifest),
                "--records-path",
                str(records_path),
                "--neo4j-password",
                "test-password",
                "--exact-prefix",
                "concept:",
                "--dry-run",
                "--output-json",
                str(dry_run_output),
            ]
        )
        == 0
    )
    dry_report = json.loads(dry_run_output.read_text(encoding="utf-8"))
    assert dry_report["summary"]["candidate_rows"] == 1
    assert dry_report["summary"]["needs_migration"] == 1
    assert dry_report["results_sample"][0]["new_target_id"] == "concept:ci_processing"
    assert dry_report["results_sample"][0]["run_mention_target_ids"] == [
        "task:subfamily:sf_social_perception_attention"
    ]

    assert (
        migrate_exact_ids.main(
            [
                "--manifest",
                str(manifest),
                "--records-path",
                str(records_path),
                "--neo4j-password",
                "test-password",
                "--exact-prefix",
                "concept:",
                "--output-json",
                str(apply_output),
            ]
        )
        == 0
    )
    apply_report = json.loads(apply_output.read_text(encoding="utf-8"))
    assert apply_report["summary"]["candidate_rows"] == 1
    assert apply_report["summary"]["migrated"] == 1
    assert apply_results[0]["new_target_id"] == "concept:ci_processing"
