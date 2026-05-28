from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_task_panel_drift_adjudication_pack import main


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_task_panel_drift_adjudication_pack_groups_actions(
    tmp_path: Path, monkeypatch
) -> None:
    review_pack = tmp_path / "drift_review_pack.jsonl"
    output_dir = tmp_path / "adjudication"
    _write_jsonl(
        review_pack,
        [
            {
                "review_bucket": "1_neurostore_task",
                "paper_id": "pmid:1",
                "claim_id": "claim:1",
                "run_id": "run:1",
                "old_task_id": "task:onvoc:onvoc_0000466",
                "current_target_id": "neurostore_task:SL5Qq3YkFSAD:fmri:0",
                "current_target_namespace": "neurostore_task",
                "current_target_label": "Cognitive Inhibition",
                "mapping_original": "concept:attention",
                "onvoc_label": "Cognitive Inhibition",
                "paper_title": "Attention paper",
            },
            {
                "review_bucket": "1_neurostore_task",
                "paper_id": "pmid:2",
                "claim_id": "claim:2",
                "run_id": "run:2",
                "old_task_id": "task:subfamily:sf_affect_induction",
                "current_target_id": "neurostore_task:55joBd4TMrva:fmri:0",
                "current_target_namespace": "neurostore_task",
                "current_target_label": "Emotion Regulation",
                "mapping_original": "concept:viewing",
                "onvoc_label": "Emotion Regulation",
                "paper_title": "Viewing paper",
            },
            {
                "review_bucket": "2_task_onvoc",
                "paper_id": "pmid:3",
                "claim_id": "claim:3",
                "run_id": "run:3",
                "old_task_id": "task:subfamily:sf_risk_ambiguity",
                "current_target_id": "task:onvoc:onvoc_0000428",
                "current_target_namespace": "task:onvoc",
                "current_target_label": "Decision Making",
                "mapping_original": "concept:decision_making",
                "onvoc_label": "Decision Making",
                "paper_title": "Decision paper",
            },
            {
                "review_bucket": "2_task_onvoc",
                "paper_id": "pmid:4",
                "claim_id": "claim:4",
                "run_id": "run:4",
                "old_task_id": "task:subfamily:sf_spatial_orienting_cueing",
                "current_target_id": "task:onvoc:onvoc_0000443",
                "current_target_namespace": "task:onvoc",
                "current_target_label": "Spatial Attention",
                "mapping_original": "concept:social_attention",
                "onvoc_label": "Spatial Attention",
                "paper_title": "Social attention paper",
            },
        ],
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_task_panel_drift_adjudication_pack.py",
            "--review-pack",
            str(review_pack),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert main() == 0

    summary = json.loads(
        (output_dir / "drift_adjudication_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["review_rows"] == 4
    assert summary["counts_by_action"] == [
        ["review_default_reject", 2],
        ["keep_namespace_replacement", 1],
        ["review_semantic_coarsening", 1],
    ]

    rows = [
        json.loads(line)
        for line in (output_dir / "drift_adjudication_pack.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    by_claim = {row["claim_id"]: row for row in rows}
    assert by_claim["claim:1"]["proposed_action"] == "keep_namespace_replacement"
    assert by_claim["claim:2"]["proposed_action"] == "review_semantic_coarsening"
    assert by_claim["claim:3"]["decision_reason"] == (
        "subfamily_collapsed_to_generic_decision_making"
    )
    assert by_claim["claim:4"]["decision_reason"] == (
        "subfamily_collapsed_to_generic_onvoc"
    )
    assert (output_dir / "keep_namespace_replacement.jsonl").exists()
    assert (output_dir / "review_semantic_coarsening.jsonl").exists()
    assert (output_dir / "review_default_reject.jsonl").exists()
