from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl import build_task_panel_cleanup_guardrail as guardrail


def test_build_task_panel_cleanup_guardrail_unions_claim_id_lists(tmp_path: Path) -> None:
    base_list = tmp_path / "protected_claim_ids.txt"
    keep_list = tmp_path / "keep_exception_claim_ids.txt"
    output_dir = tmp_path / "guardrail"

    base_list.write_text("claim:a\nclaim:b\n", encoding="utf-8")
    keep_list.write_text("claim:b\nclaim:c\n", encoding="utf-8")

    assert (
        guardrail.main(
            [
                "--claim-id-list",
                str(base_list),
                "--claim-id-list",
                str(keep_list),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    combined = (output_dir / "cleanup_guardrail_claim_ids.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert combined == ["claim:a", "claim:b", "claim:c"]

    summary = json.loads(
        (output_dir / "cleanup_guardrail_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"] == {"input_lists": 2, "combined_claim_ids": 3}
