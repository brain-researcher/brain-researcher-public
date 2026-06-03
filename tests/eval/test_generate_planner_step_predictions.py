"""Tests for planner-step prediction artifact generation."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "generate_planner_step_predictions.py"
SPEC = importlib.util.spec_from_file_location(
    "generate_planner_step_predictions", SCRIPT_PATH
)
assert SPEC is not None
assert SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _fake_planner(request_payload: dict[str, Any]) -> dict[str, Any]:
    query = request_payload["query"]
    if "no plan" in query:
        return {"dag": {"steps": []}, "candidates": [{"tool_id": "ranked.not.used"}]}
    return {
        "plan_id": "plan-1",
        "dag": {
            "steps": [
                {"id": "s1", "tool": "first_tool"},
                {"id": "s2", "tool_id": "second_tool"},
            ]
        },
        "candidates": [
            {"tool_id": "ranked.not.used"},
            {"tool_id": "also.not.used"},
        ],
    }


def test_run_predictions_extracts_ordered_plan_steps_only(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "SEQ-1",
                "query": "Run a two step fMRI workflow",
                "category": "Workflow",
                "exact_labels": {
                    "expected_sequence_tool_ids": ["first_tool", "second_tool"]
                },
            },
            {
                "task_id": "NOSEQ-1",
                "query": "Single tool task",
                "exact_labels": {"expected_sequence_tool_ids": []},
            },
        ],
    )

    payload = generator.run_predictions(
        labels_jsonl=labels,
        max_tasks=None,
        mode="test_mode",
        planner_surface="fake",
        allowlist_mode="diagnostic",
        planner_fn=_fake_planner,
    )

    assert payload["summary"]["labels_loaded"] == 2
    assert payload["summary"]["selected_label_rows"] == 1
    assert payload["summary"]["rows_with_planner_steps"] == 1
    prediction = payload["predictions"][0]
    assert prediction["task_id"] == "SEQ-1"
    assert prediction["mode"] == "test_mode"
    assert prediction["prediction_kind"] == "planning_only"
    assert prediction["analysis_executed"] is False
    assert prediction["flat_ranked_list_prediction"] is False
    assert prediction["planner_step_tool_ids"] == ["first_tool", "second_tool"]
    assert "top_tool_ids" not in prediction
    assert "predicted_tool_ids" not in prediction
    assert "candidates" not in prediction["plan"]
    assert prediction["planner_raw_summary"]["raw_candidate_count"] == 2


def test_run_predictions_records_no_steps_and_errors(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "SEQ-NO-STEPS",
                "query": "no plan for this task",
                "exact_labels": {"expected_sequence_tool_ids": ["expected"]},
            },
            {
                "task_id": "SEQ-ERROR",
                "query": "raise error",
                "exact_labels": {"expected_sequence_tool_ids": ["expected"]},
            },
        ],
    )

    def fake_planner(request_payload: dict[str, Any]) -> dict[str, Any]:
        if request_payload["query"] == "raise error":
            raise RuntimeError("planner unavailable")
        return _fake_planner(request_payload)

    payload = generator.run_predictions(
        labels_jsonl=labels,
        max_tasks=None,
        mode="test_mode",
        planner_surface="fake",
        allowlist_mode="curated",
        planner_fn=fake_planner,
    )

    summary = payload["summary"]
    assert summary["rows_with_planner_steps"] == 0
    assert summary["rows_without_planner_steps"] == 1
    assert summary["rows_with_errors"] == 1
    by_task = {row["task_id"]: row for row in payload["predictions"]}
    assert by_task["SEQ-NO-STEPS"]["planner_status"] == "no_steps"
    assert by_task["SEQ-NO-STEPS"]["planner_step_tool_ids"] == []
    assert by_task["SEQ-ERROR"]["planner_status"] == "error"
    assert "planner unavailable" in by_task["SEQ-ERROR"]["planner_error"]


def test_main_writes_jsonl_and_summary_with_fake_planner(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    labels = tmp_path / "labels.jsonl"
    out_dir = tmp_path / "out"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "SEQ-1",
                "query": "Run a two step fMRI workflow",
                "exact_labels": {
                    "expected_sequence_tool_ids": ["first_tool", "second_tool"]
                },
            }
        ],
    )
    monkeypatch.setattr(
        generator,
        "_planner_for_surface",
        lambda *args, **kwargs: _fake_planner,
    )

    exit_code = generator.main(
        [
            "--labels-jsonl",
            str(labels),
            "--output-dir",
            str(out_dir),
            "--planner-surface",
            "local-agent-plan",
            "--max-tasks",
            "1",
        ]
    )

    assert exit_code == 0
    predictions = [
        json.loads(line)
        for line in (out_dir / "planner_step_predictions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert predictions[0]["planner_step_tool_ids"] == ["first_tool", "second_tool"]
    assert predictions[0]["planner_surface"] == "local-agent-plan"
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["planning_only"] is True
    assert summary["flat_ranked_list_predictions_used"] is False
    printed = json.loads(capsys.readouterr().out)
    assert printed["output_jsonl"].endswith("planner_step_predictions.jsonl")


def test_load_runtime_env_preserves_existing_values(
    tmp_path: Path, monkeypatch: Any
) -> None:
    env_file = tmp_path / ".env"
    env_local = tmp_path / ".env.local"
    env_file.write_text(
        "BR_TEST_FROM_ENV=loaded\nBR_TEST_EXISTING=from_env\n",
        encoding="utf-8",
    )
    env_local.write_text("BR_TEST_FROM_LOCAL=loaded_local\n", encoding="utf-8")
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setenv("BR_TEST_EXISTING", "already_set")
    monkeypatch.delenv("BR_TEST_FROM_ENV", raising=False)
    monkeypatch.delenv("BR_TEST_FROM_LOCAL", raising=False)

    generator._load_runtime_env()

    assert os.environ["BR_TEST_FROM_ENV"] == "loaded"
    assert os.environ["BR_TEST_FROM_LOCAL"] == "loaded_local"
    assert os.environ["BR_TEST_EXISTING"] == "already_set"
