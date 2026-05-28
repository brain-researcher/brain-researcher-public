from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_task_panel_drift_exception_pack as drift_exception


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_drift_exception_pack_classifies_residual_rows(
    tmp_path: Path,
) -> None:
    adjudication_pack = tmp_path / "drift_adjudication_pack.jsonl"
    protected_claim_ids = tmp_path / "protected_claim_ids.txt"
    output_dir = tmp_path / "drift_exception_pack"

    _write_jsonl(
        adjudication_pack,
        [
            {
                "claim_id": "claim:protected",
                "paper_id": "pmid:1",
                "run_id": "run:1",
                "old_task_id": "task:onvoc:onvoc_0000466",
                "current_target_id": "neurostore_task:SL5Qq3YkFSAD:fmri:0",
                "current_target_label": "Cognitive Inhibition",
                "onvoc_label": "Cognitive Inhibition",
                "mapping_original": "concept:attention",
                "proposed_action": "keep_namespace_replacement",
            },
            {
                "claim_id": "claim:keep",
                "paper_id": "pmid:2",
                "run_id": "run:2",
                "old_task_id": "task:subfamily:sf_affect_induction",
                "current_target_id": drift_exception.EMOTION_REGULATION_CURRENT_ID,
                "mapping_original": "concept:emotional_regulation",
                "proposed_action": "review_semantic_coarsening",
            },
            {
                "claim_id": "claim:manual",
                "paper_id": "pmid:3",
                "run_id": "run:3",
                "old_task_id": "task:subfamily:sf_item_recognition",
                "current_target_id": drift_exception.EPISODIC_MEMORY_CURRENT_ID,
                "mapping_original": "concept:movie",
                "proposed_action": "review_semantic_coarsening",
            },
            {
                "claim_id": "claim:reject-semantic",
                "paper_id": "pmid:4",
                "run_id": "run:4",
                "old_task_id": "task:subfamily:sf_affect_induction",
                "current_target_id": drift_exception.EMOTION_REGULATION_CURRENT_ID,
                "mapping_original": "concept:viewing",
                "proposed_action": "review_semantic_coarsening",
            },
            {
                "claim_id": "claim:reject-default",
                "paper_id": "pmid:5",
                "run_id": "run:5",
                "old_task_id": "task:subfamily:sf_risk_ambiguity",
                "current_target_id": "task:onvoc:onvoc_0000428",
                "mapping_original": "concept:decision_making",
                "proposed_action": "review_default_reject",
            },
            {
                "claim_id": "claim:tail",
                "paper_id": "pmid:6",
                "run_id": "run:6",
                "old_task_id": "task:subfamily:sf_wm_updating_streaming",
                "current_target_id": "neurostore_task:7CHG5JsyUddj:fmri:1",
                "mapping_original": "concept:working_memory",
                "proposed_action": "review_semantic_coarsening",
            },
        ],
    )
    protected_claim_ids.write_text("claim:protected\n", encoding="utf-8")

    assert (
        drift_exception.main(
            [
                "--adjudication-pack",
                str(adjudication_pack),
                "--protected-claim-ids",
                str(protected_claim_ids),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    summary = json.loads(
        (output_dir / "drift_exception_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"] == {
        "residual_rows": 5,
        "keep_exception_rows": 1,
        "manual_review_rows": 2,
        "reject_default_rows": 2,
        "keep_exception_claim_ids": 1,
        "manual_review_claim_ids": 2,
        "reject_default_claim_ids": 2,
    }

    keep_ids = (output_dir / "keep_exception_claim_ids.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert keep_ids == ["claim:keep"]
    manual_ids = (output_dir / "manual_review_claim_ids.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert manual_ids == ["claim:manual", "claim:tail"]
    reject_ids = (output_dir / "reject_default_claim_ids.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert reject_ids == ["claim:reject-default", "claim:reject-semantic"]
