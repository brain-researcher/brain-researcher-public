"""Regression tests for planner-step sequence routing evaluation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "evaluate_planner_sequence_routing.py"
SPEC = importlib.util.spec_from_file_location(
    "evaluate_planner_sequence_routing", SCRIPT_PATH
)
assert SPEC is not None
assert SPEC.loader is not None
planner_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner_eval)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_planner_step_sequence_scores_plan_steps_not_flat_ranked_lists(
    tmp_path: Path,
) -> None:
    labels = tmp_path / "labels.jsonl"
    predictions = tmp_path / "predictions.json"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "SEQ-1",
                "category": "preproc",
                "exact_labels": {
                    "expected_sequence_tool_ids": ["tool.a", "tool.b", "tool.c"],
                },
            },
            {
                "task_id": "SEQ-2",
                "category": "stats",
                "exact_labels": {
                    "expected_sequence_tool_ids": ["tool.c", "tool.d"],
                },
            },
            {
                "task_id": "SEQ-3",
                "category": "stats",
                "exact_labels": {
                    "expected_sequence_tool_ids": ["tool.z"],
                },
            },
            {
                "task_id": "NOSEQ",
                "category": "single",
                "exact_labels": {"expected_tool_ids": ["tool.a"]},
            },
        ],
    )
    predictions.write_text(
        json.dumps(
            {
                "predictions": [
                    {
                        "task_id": "SEQ-1",
                        "planner_step_tool_ids": [
                            "tool.a",
                            "tool.x",
                            "tool.b",
                            "tool.c",
                        ],
                        "top_tool_ids": ["not.used"],
                    },
                    {
                        "task_id": "SEQ-2",
                        "plan": {
                            "dag": {
                                "steps": [
                                    {"id": "s1", "tool": "tool.d"},
                                    {"id": "s2", "tool": "tool.c"},
                                ]
                            }
                        },
                    },
                    {"task_id": "SEQ-3", "top_tool_ids": ["tool.z"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = planner_eval.evaluate(
        labels_jsonl=labels,
        predictions_json=predictions,
    )

    summary = payload["summary"]
    assert summary["metric_surface"] == "planner_step_sequence"
    assert summary["flat_ranked_list_metrics_evaluated"] is False
    assert summary["sequence_label_rows"] == 3
    assert summary["evaluated_tasks"] == 2
    assert summary["skipped_missing_planner_step_predictions"] == 1
    assert summary["planner_step_ordered_sequence_recall"] == 0.5
    assert summary["planner_step_ordered_step_coverage_mean"] == 0.75
    assert summary["planner_step_unordered_step_coverage_mean"] == 1.0
    assert summary["planner_step_exact_sequence_match_rate"] == 0.0
    assert summary["rows_with_flat_ranked_fields_ignored"] == 1

    by_task = {row["task_id"]: row for row in payload["rows"]}
    assert by_task["SEQ-1"]["predicted_planner_step_tool_ids"] == [
        "tool.a",
        "tool.x",
        "tool.b",
        "tool.c",
    ]
    assert by_task["SEQ-1"]["planner_step_ordered_sequence_recalled"] is True
    assert by_task["SEQ-1"]["prediction_source"] == "planner_step_tool_ids"
    assert by_task["SEQ-2"]["predicted_planner_step_tool_ids"] == [
        "tool.d",
        "tool.c",
    ]
    assert by_task["SEQ-2"]["planner_step_ordered_step_coverage"] == 0.5
    assert by_task["SEQ-2"]["prediction_source"] == "plan.dag.steps"


def test_load_predictions_accepts_jsonl_and_mode_filter(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {
                "task_id": "SEQ-1",
                "mode": "planner",
                "step_tool_ids": ["tool.a", "tool.b"],
            },
            {
                "task_id": "SEQ-1",
                "mode": "flat",
                "step_tool_ids": ["wrong"],
            },
            {
                "task_id": "SEQ-2",
                "mode": "planner",
                "planner_output": {
                    "dag": {"steps": [{"tool_id": "tool.c"}, {"tool_id": "tool.d"}]}
                },
            },
        ],
    )

    loaded = planner_eval.load_predictions(predictions, mode="planner")

    assert loaded == {
        "SEQ-1": {
            "planner_step_tool_ids": ["tool.a", "tool.b"],
            "prediction_source": "step_tool_ids",
            "raw_has_flat_ranked_fields": False,
        },
        "SEQ-2": {
            "planner_step_tool_ids": ["tool.c", "tool.d"],
            "prediction_source": "planner_output.dag.steps",
            "raw_has_flat_ranked_fields": False,
        },
    }


def test_cli_writes_json_and_csv_outputs(tmp_path: Path, capsys: Any) -> None:
    labels = tmp_path / "labels.jsonl"
    predictions = tmp_path / "predictions.json"
    out_json = tmp_path / "out" / "eval.json"
    out_csv = tmp_path / "out" / "eval.csv"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "SEQ-1",
                "exact_labels": {
                    "expected_sequence_tool_ids": ["tool.a", "tool.b"],
                },
            }
        ],
    )
    predictions.write_text(
        json.dumps({"SEQ-1": ["tool.a", "tool.b"]}),
        encoding="utf-8",
    )

    exit_code = planner_eval.main(
        [
            "--labels-jsonl",
            str(labels),
            "--predictions-json",
            str(predictions),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
        ]
    )

    assert exit_code == 0
    assert (
        json.loads(out_json.read_text(encoding="utf-8"))["summary"][
            "planner_step_ordered_sequence_recall"
        ]
        == 1.0
    )
    assert "predicted_planner_step_tool_ids" in out_csv.read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out)["evaluated_tasks"] == 1
