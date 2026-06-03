"""Regression tests for sequence tool-label auditing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "audit_sequence_tool_labels.py"
SPEC = importlib.util.spec_from_file_location("audit_sequence_tool_labels", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
sequence_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sequence_audit)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_ordered_subsequence_and_step_coverage_helpers() -> None:
    predicted = ["tool.a", "tool.x", "tool.b", "tool.c"]
    expected = ["tool.a", "tool.b", "tool.c"]

    assert sequence_audit.ordered_subsequence_at_k(predicted, expected, 2) is False
    assert sequence_audit.ordered_subsequence_at_k(predicted, expected, 4) is True
    assert sequence_audit.ordered_step_match_count_at_k(predicted, expected, 3) == 2
    assert sequence_audit.ordered_step_coverage_at_k(predicted, expected, 3) == 2 / 3
    assert sequence_audit.ordered_step_coverage_at_k(predicted, [], 3) is None


def test_analyze_sequence_labels_reports_conflicts_and_metric_limits() -> None:
    rows = [
        {
            "_line_number": 1,
            "task_id": "SEQ-1",
            "category": "Preprocessing",
            "query": "Run A then B then C.",
            "exact_labels": {
                "expected_tool_ids": ["tool.a", "tool.b"],
                "expected_sequence_tool_ids": ["tool.a", "tool.b", "tool.c"],
            },
        },
        {
            "_line_number": 2,
            "task_id": "SEQ-2",
            "category": "QC",
            "query": "Run D after C.",
            "exact_labels": {
                "expected_tool_ids": ["tool.c", "tool.extra"],
                "expected_sequence_tool_ids": ["tool.c", "tool.d"],
            },
        },
        {
            "_line_number": 3,
            "task_id": "NOSEQ",
            "category": "QC",
            "query": "Single tool.",
            "exact_labels": {"expected_tool_ids": ["tool.a"]},
        },
    ]

    payload = sequence_audit.analyze_sequence_labels(
        rows,
        catalog_tool_ids={"tool.a", "tool.b", "tool.c"},
        k_values=[1, 3],
        suspect_limit=5,
    )

    summary = payload["summary"]
    assert summary["total_rows"] == 3
    assert summary["sequence_rows"] == 2
    assert summary["sequence_length_distribution"] == {"2": 1, "3": 1}
    assert summary["invalid_sequence_tool_id_count"] == 1
    assert summary["rows_with_expected_sequence_conflicts"] == 2
    assert summary["likely_metric_impossible_top_1_count"] == 2
    assert summary["likely_metric_impossible_top_3_count"] == 0
    assert summary["ordered_subsequence_at_1_max_possible_from_labels"] == 0.0
    assert summary["ordered_subsequence_at_3_max_possible_from_labels"] == 1.0

    assert payload["invalid_sequence_tool_ids"] == [
        {
            "line_number": 2,
            "task_id": "SEQ-2",
            "category": "QC",
            "invalid_tool_id": "tool.d",
        }
    ]
    assert payload["expected_sequence_conflicts"][0]["task_id"] == "SEQ-1"
    assert payload["expected_sequence_conflicts"][0][
        "sequence_ids_missing_from_expected_tool_ids"
    ] == ["tool.c"]
    assert {row["task_id"] for row in payload["representative_suspect_rows"]} == {
        "SEQ-1",
        "SEQ-2",
    }


def test_load_jsonl_adds_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"
    _write_jsonl(
        path,
        [
            {
                "task_id": "A",
                "exact_labels": {"expected_sequence_tool_ids": ["tool.a"]},
            },
            {
                "task_id": "B",
                "exact_labels": {"expected_sequence_tool_ids": ["tool.b"]},
            },
        ],
    )

    rows = sequence_audit._load_jsonl(path)

    assert [row["_line_number"] for row in rows] == [1, 2]
