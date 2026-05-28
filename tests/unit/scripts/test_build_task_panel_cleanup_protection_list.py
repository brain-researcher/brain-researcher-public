from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_task_panel_cleanup_protection_list import main


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_cleanup_protection_list_filters_actions(
    tmp_path: Path, monkeypatch
) -> None:
    adjudication_pack = tmp_path / "drift_adjudication_pack.jsonl"
    output_dir = tmp_path / "protection"
    _write_jsonl(
        adjudication_pack,
        [
            {
                "claim_id": "claim:1",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "proposed_action": "keep_namespace_replacement",
                "old_task_id": "task:onvoc:onvoc_0000466",
                "current_target_id": "neurostore_task:1",
                "mapping_original": "concept:attention",
                "decision_reason": "namespace_only_same_public_label",
                "paper_title": "Attention paper",
            },
            {
                "claim_id": "claim:2",
                "paper_id": "pmid:2",
                "run_id": "run:2",
                "proposed_action": "review_default_reject",
                "old_task_id": "task:subfamily:sf_risk_ambiguity",
                "current_target_id": "task:onvoc:onvoc_0000428",
                "mapping_original": "concept:decision_making",
                "decision_reason": "subfamily_collapsed_to_generic_decision_making",
                "paper_title": "Decision paper",
            },
        ],
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_task_panel_cleanup_protection_list.py",
            "--adjudication-pack",
            str(adjudication_pack),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert main() == 0

    summary = json.loads(
        (output_dir / "cleanup_protection_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"] == {"protected_rows": 1, "protected_claim_ids": 1}
    assert summary["counts_by_current_target_id"] == [["neurostore_task:1", 1]]

    protected_ids = (output_dir / "protected_claim_ids.txt").read_text(encoding="utf-8")
    assert protected_ids == "claim:1\n"
