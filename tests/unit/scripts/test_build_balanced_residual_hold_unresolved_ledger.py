from __future__ import annotations

import json
from pathlib import Path

from scripts.tools.etl.build_balanced_residual_hold_unresolved_ledger import (
    build_ledger_rows,
    main,
    parse_args,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_residual_ledger_rows(tmp_path: Path) -> None:
    task_region_unresolved = tmp_path / "task_region_unresolved.jsonl"
    task_region_parse_errors = tmp_path / "task_region_parse_errors.jsonl"
    task_region_title_only_rejected = tmp_path / "task_region_title_only_rejected.jsonl"
    specific_concept_unresolved = tmp_path / "specific_concept_unresolved.jsonl"
    biomarker_unresolved = tmp_path / "biomarker_unresolved.jsonl"
    broad_biomarker_hold = tmp_path / "broad_biomarker_hold.jsonl"
    broad_trait_hold = tmp_path / "broad_trait_hold.jsonl"
    manual_concept_review = tmp_path / "manual_concept_review.jsonl"

    _write_jsonl(
        task_region_unresolved,
        [
            {
                "paper_id": "paper:1",
                "paper_title": "Task paper",
                "target_id": "task:1",
                "target_label": "Task One",
                "target_type": "Task",
                "reason": "publication_unresolved_or_no_non_title_text",
            }
        ],
    )
    _write_jsonl(
        task_region_parse_errors,
        [
            {
                "paper_id": "paper:2",
                "paper_title": "Parse paper",
                "target_id": "region:1",
                "target_label": "Region One",
                "target_type": "Region",
                "error": "bad json",
                "failure_reason": "empty_response",
            }
        ],
    )
    _write_jsonl(
        task_region_title_only_rejected,
        [
            {
                "paper_id": "paper:3",
                "paper_title": "Title only paper",
                "target_id": "region:2",
                "target_label": "Region Two",
                "target_type": "Region",
                "reason": "llm_returned_title_only_after_regeneration",
            }
        ],
    )
    _write_jsonl(
        specific_concept_unresolved,
        [
            {
                "paper_id": "paper:4",
                "paper_title": "Concept paper",
                "target_id": "concept:1",
                "target_label": "Concept One",
                "target_type": "Concept",
                "reason": "publication_unresolved_or_no_non_title_text",
            }
        ],
    )
    _write_jsonl(
        biomarker_unresolved,
        [
            {
                "paper_id": "paper:5",
                "paper_title": "Biomarker paper",
                "target_id": "concept:2",
                "target_label": "Biomarker One",
                "target_type": "Concept",
                "reason": "publication_unresolved_or_no_non_title_text",
            }
        ],
    )
    _write_jsonl(
        broad_biomarker_hold,
        [
            {
                "paper_id": "paper:6",
                "paper_title": "Amyloid paper",
                "claim_id": "claim:6",
                "run_id": "run:6",
                "target_id": "concept:amyloid",
                "target_label": "Amyloid",
                "target_type": "Concept",
                "policy_bucket": "broad_biomarker_hold",
                "source_review_bucket": "scope_review_clinical_or_biomarker",
            }
        ],
    )
    _write_jsonl(
        broad_trait_hold,
        [
            {
                "paper_id": "paper:7",
                "paper_title": "Trait paper",
                "claim_id": "claim:7",
                "run_id": "run:7",
                "target_id": "concept:trait",
                "target_label": "Trait One",
                "target_type": "Concept",
                "policy_bucket": "broad_trait_hold",
                "source_review_bucket": "scope_review_clinical_or_biomarker",
            }
        ],
    )
    _write_jsonl(
        manual_concept_review,
        [
            {
                "paper_id": "paper:8",
                "paper_title": "Manual concept paper",
                "claim_id": "claim:8",
                "run_id": "run:8",
                "target_id": "concept:manual",
                "target_label": "Manual Concept",
                "target_type": "Concept",
                "adjudication_bucket": "manual_concept_review",
            }
        ],
    )

    args = parse_args(
        [
            "--task-region-unresolved",
            str(task_region_unresolved),
            "--task-region-parse-errors",
            str(task_region_parse_errors),
            "--task-region-title-only-rejected",
            str(task_region_title_only_rejected),
            "--specific-concept-unresolved",
            str(specific_concept_unresolved),
            "--biomarker-unresolved",
            str(biomarker_unresolved),
            "--broad-biomarker-hold",
            str(broad_biomarker_hold),
            "--broad-trait-hold",
            str(broad_trait_hold),
            "--manual-concept-review",
            str(manual_concept_review),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    rows = build_ledger_rows(args)
    assert len(rows) == 8
    assert sum(row["entry_kind"] == "hold" for row in rows) == 3
    assert sum(row["entry_kind"] == "unresolved" for row in rows) == 5
    buckets = {row["ledger_bucket"] for row in rows}
    assert "broad_biomarker_hold" in buckets
    assert "task_region_parse_error" in buckets
    assert "specific_concept_unresolved_no_non_title_text" in buckets
    parse_row = next(row for row in rows if row["ledger_bucket"] == "task_region_parse_error")
    assert parse_row["recommended_next_action"] == "retry_with_provider_or_transport_hardening"
    assert parse_row["blocking_reason"] == "empty_response_during_task_region_regeneration"


def test_build_residual_ledger_main(tmp_path: Path) -> None:
    input_paths = {}
    for name in [
        "task_region_unresolved",
        "task_region_parse_errors",
        "task_region_title_only_rejected",
        "specific_concept_unresolved",
        "biomarker_unresolved",
        "broad_biomarker_hold",
        "broad_trait_hold",
        "manual_concept_review",
    ]:
        path = tmp_path / f"{name}.jsonl"
        input_paths[name] = path
        _write_jsonl(path, [])

    _write_jsonl(
        input_paths["broad_trait_hold"],
        [
            {
                "paper_id": "paper:9",
                "paper_title": "Trait paper",
                "claim_id": "claim:9",
                "run_id": "run:9",
                "target_id": "concept:trait",
                "target_label": "Trait One",
                "target_type": "Concept",
            }
        ],
    )

    output_dir = tmp_path / "out"
    argv = []
    for key, path in input_paths.items():
        argv.extend([f"--{key.replace('_', '-')}", str(path)])
    argv.extend(["--output-dir", str(output_dir)])

    assert main(argv) == 0

    summary = json.loads(
        (output_dir / "residual_ledger_summary.json").read_text(encoding="utf-8")
    )
    assert summary["counts"]["rows_total"] == 1
    assert summary["counts"]["hold_rows_total"] == 1
    assert summary["counts"]["unresolved_rows_total"] == 0
    assert summary["counts"]["broad_behavioral_trait_hold"] == 1
    ledger_lines = (output_dir / "residual_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger_lines) == 1
