from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_residual_retry_now_pack import main


def test_build_balanced_residual_retry_now_pack(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    rows = [
        {
            "paper_id": "paper:1",
            "paper_title": "Parse row",
            "claim_id": "claim:1",
            "run_id": "run:1",
            "target_type": "Region",
            "target_id": "region:one",
            "target_label": "Region One",
            "evidence_section": "title",
            "source_review_bucket": "salvage_task_or_region",
            "source_bucket_reason": "title_only_after_retry",
            "rejection_reasons": ["benchmark_title_only_suppressed"],
            "mapping_confidence": 0.1,
            "claim_strength": 0.2,
            "method_rigor": 0.0,
            "ledger_bucket": "task_region_parse_error",
            "source_stage": "balanced_title_only_regeneration_run",
            "source_artifact_path": "/tmp/a.jsonl",
            "retry_mode": "retry_now",
            "recommended_next_action": "retry_with_json_repair_hardening",
            "blocking_reason": "parse_error",
        },
        {
            "paper_id": "paper:2",
            "paper_title": "Hold row",
            "target_type": "Concept",
            "target_id": "concept:two",
            "target_label": "Concept Two",
            "ledger_bucket": "manual_concept_review",
        },
    ]
    ledger_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    assert main(["--residual-ledger", str(ledger_path), "--output-dir", str(output_dir)]) == 0

    summary = json.loads((output_dir / "retry_now_pack_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["rows_total"] == 1
    assert summary["counts"]["task_region_parse_error"] == 1
    packed = (output_dir / "retry_now_pack.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(packed) == 1
    row = json.loads(packed[0])
    assert row["claim_id"] == "claim:1"
    assert row["run_id"] == "run:1"
