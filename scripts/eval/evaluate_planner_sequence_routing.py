#!/usr/bin/env python3
"""Evaluate curated sequence labels against planner-step predictions.

This is an instrumentation-only evaluator for the planner sequence surface.
It does not instantiate the production planner, does not call live services,
and does not change routing behavior.

Reliable offline mode:

    python scripts/eval/evaluate_planner_sequence_routing.py \
      --predictions-json planner_step_predictions.jsonl \
      --out-json planner_step_sequence_eval.json

The predictions file may be JSON or JSONL. It must provide a task_id plus an
ordered planner-step tool sequence, either explicitly:

    {"task_id": "T1", "planner_step_tool_ids": ["tool.a", "tool.b"]}

or as a plan payload:

    {"task_id": "T1", "plan": {"dag": {"steps": [{"tool": "tool.a"}]}}}

Flat ranked-list fields such as top_tool_ids and predicted_tool_ids are
deliberately ignored by this evaluator.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LABELS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "microtooling_exact_labels.manual_curated.v2.labels.jsonl"
)

STEP_SEQUENCE_FIELDS = (
    "planner_step_tool_ids",
    "predicted_planner_step_tool_ids",
    "plan_step_tool_ids",
    "step_tool_ids",
    "predicted_step_tool_ids",
)
PLAN_CONTAINER_FIELDS = (
    "plan",
    "planner_output",
    "plan_payload",
    "planner_plan",
    "prediction",
)
STEP_LIST_FIELDS = ("steps", "plan_steps")
STEP_TOOL_FIELDS = ("tool", "tool_id", "toolId", "canonical_tool_id", "tool_name")
ROW_LIST_FIELDS = ("predictions", "planner_predictions", "results", "rows")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        raw = value
    else:
        raw = re.split(r"[,;]", str(value))
    return [str(item).strip() for item in raw if str(item).strip()]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append({**row, "_line_number": line_number})
    return rows


def _load_json_or_jsonl(path: Path) -> Any:
    if path.suffix == ".jsonl":
        return _load_jsonl(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _exact_sequence(row: Mapping[str, Any]) -> list[str]:
    exact = row.get("exact_labels")
    if not isinstance(exact, Mapping):
        return []
    return _as_list(exact.get("expected_sequence_tool_ids"))


def _label_sequence_rows(path: Path) -> list[dict[str, Any]]:
    rows = _load_jsonl(path)
    return [row for row in rows if _exact_sequence(row)]


def _step_tool_from_step(step: Any) -> str | None:
    if isinstance(step, str):
        text = step.strip()
        return text or None
    if not isinstance(step, Mapping):
        return None
    for field in STEP_TOOL_FIELDS:
        text = str(step.get(field) or "").strip()
        if text:
            return text
    return None


def _extract_from_step_list(steps: Any) -> list[str]:
    if not isinstance(steps, list):
        return []
    out: list[str] = []
    for step in steps:
        tool_id = _step_tool_from_step(step)
        if tool_id:
            out.append(tool_id)
    return out


def _extract_from_plan_payload(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return []

    dag = payload.get("dag")
    if isinstance(dag, Mapping):
        extracted = _extract_from_step_list(dag.get("steps"))
        if extracted:
            return extracted

    for field in STEP_LIST_FIELDS:
        extracted = _extract_from_step_list(payload.get(field))
        if extracted:
            return extracted
    return []


def extract_planner_step_tool_ids(
    payload: Mapping[str, Any],
) -> tuple[list[str], str | None]:
    """Extract ordered planner-step tool IDs from a prediction row.

    Ranked-list fields are intentionally not considered. The returned source is
    the field or plan container that supplied the sequence.
    """
    for field in STEP_SEQUENCE_FIELDS:
        extracted = _as_list(payload.get(field))
        if extracted:
            return extracted, field

    extracted = _extract_from_plan_payload(payload)
    if extracted:
        return extracted, "dag.steps"

    for field in PLAN_CONTAINER_FIELDS:
        nested = payload.get(field)
        extracted = _extract_from_plan_payload(nested)
        if extracted:
            return extracted, f"{field}.dag.steps"

    return [], None


def _prediction_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if not isinstance(payload, Mapping):
        return []

    for field in ROW_LIST_FIELDS:
        rows = payload.get(field)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    if payload.get("task_id"):
        return [dict(payload)]

    rows: list[dict[str, Any]] = []
    for task_id, value in payload.items():
        if isinstance(value, Mapping):
            rows.append({"task_id": task_id, **dict(value)})
        elif isinstance(value, list | tuple | set) or isinstance(value, str):
            rows.append({"task_id": task_id, "planner_step_tool_ids": value})
    return rows


def load_predictions(
    path: Path, *, mode: str | None = None
) -> dict[str, dict[str, Any]]:
    payload = _load_json_or_jsonl(path)
    predictions: dict[str, dict[str, Any]] = {}
    for row in _prediction_rows(payload):
        if mode is not None and str(row.get("mode") or "") != mode:
            continue
        task_id = str(row.get("task_id") or "").strip()
        if not task_id:
            continue
        step_tool_ids, source = extract_planner_step_tool_ids(row)
        predictions[task_id] = {
            "planner_step_tool_ids": step_tool_ids,
            "prediction_source": source,
            "raw_has_flat_ranked_fields": any(
                field in row for field in ("top_tool_ids", "predicted_tool_ids")
            ),
        }
    return predictions


def ordered_match_count(
    predicted_step_tool_ids: Sequence[str],
    expected_sequence_tool_ids: Sequence[str],
) -> int:
    cursor = 0
    for tool_id in predicted_step_tool_ids:
        if (
            cursor < len(expected_sequence_tool_ids)
            and tool_id == expected_sequence_tool_ids[cursor]
        ):
            cursor += 1
    return cursor


def unordered_match_count(
    predicted_step_tool_ids: Sequence[str],
    expected_sequence_tool_ids: Sequence[str],
) -> int:
    remaining = Counter(predicted_step_tool_ids)
    matched = 0
    for tool_id in expected_sequence_tool_ids:
        if remaining[tool_id] > 0:
            matched += 1
            remaining[tool_id] -= 1
    return matched


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / float(len(values)) if values else None


def _score_row(
    label_row: Mapping[str, Any],
    prediction: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _exact_sequence(label_row)
    predicted = _as_list(prediction.get("planner_step_tool_ids"))
    ordered_count = ordered_match_count(predicted, expected)
    unordered_count = unordered_match_count(predicted, expected)
    expected_count = len(expected)
    ordered_coverage = ordered_count / float(expected_count)
    unordered_coverage = unordered_count / float(expected_count)
    return {
        "task_id": str(label_row.get("task_id") or ""),
        "line_number": label_row.get("_line_number"),
        "category": label_row.get("category"),
        "expected_sequence_tool_ids": expected,
        "predicted_planner_step_tool_ids": predicted,
        "prediction_source": prediction.get("prediction_source"),
        "raw_has_flat_ranked_fields": bool(
            prediction.get("raw_has_flat_ranked_fields")
        ),
        "planner_step_expected_step_count": expected_count,
        "planner_step_predicted_step_count": len(predicted),
        "planner_step_ordered_match_count": ordered_count,
        "planner_step_unordered_match_count": unordered_count,
        "planner_step_ordered_sequence_recalled": ordered_count == expected_count,
        "planner_step_ordered_step_coverage": ordered_coverage,
        "planner_step_unordered_step_coverage": unordered_coverage,
        "planner_step_exact_sequence_match": predicted == expected,
    }


def evaluate(
    *,
    labels_jsonl: Path,
    predictions_json: Path,
    mode: str | None = None,
    max_tasks: int | None = None,
) -> dict[str, Any]:
    label_rows = _label_sequence_rows(labels_jsonl)
    if max_tasks is not None:
        label_rows = label_rows[: max(0, max_tasks)]
    predictions = load_predictions(predictions_json, mode=mode)

    rows: list[dict[str, Any]] = []
    skipped_missing_predictions = 0
    skipped_missing_planner_step_predictions = 0
    for label_row in label_rows:
        task_id = str(label_row.get("task_id") or "").strip()
        prediction = predictions.get(task_id)
        if prediction is None:
            skipped_missing_predictions += 1
            continue
        if not prediction.get("planner_step_tool_ids"):
            skipped_missing_planner_step_predictions += 1
            continue
        rows.append(_score_row(label_row, prediction))

    sequence_recalled = [
        1.0 if row["planner_step_ordered_sequence_recalled"] else 0.0 for row in rows
    ]
    exact_matches = [
        1.0 if row["planner_step_exact_sequence_match"] else 0.0 for row in rows
    ]
    summary: dict[str, Any] = {
        "metric_surface": "planner_step_sequence",
        "flat_ranked_list_metrics_evaluated": False,
        "notes": [
            "Scores ordered tool IDs from planner steps or plan DAG steps.",
            "Does not score flat ranked-list fields such as top_tool_ids.",
            "Offline predictions input is the reliable mode; live planning is not invoked.",
        ],
        "mode": mode,
        "sequence_label_rows": len(label_rows),
        "evaluated_tasks": len(rows),
        "skipped_missing_predictions": skipped_missing_predictions,
        "skipped_missing_planner_step_predictions": (
            skipped_missing_planner_step_predictions
        ),
        "planner_step_ordered_sequence_recall": _mean(sequence_recalled),
        "planner_step_ordered_step_coverage_mean": _mean(
            [float(row["planner_step_ordered_step_coverage"]) for row in rows]
        ),
        "planner_step_unordered_step_coverage_mean": _mean(
            [float(row["planner_step_unordered_step_coverage"]) for row in rows]
        ),
        "planner_step_exact_sequence_match_rate": _mean(exact_matches),
        "rows_with_flat_ranked_fields_ignored": sum(
            1 for row in rows if row["raw_has_flat_ranked_fields"]
        ),
    }

    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({str(row.get("category") or "") for row in rows}):
        category_rows = [
            row for row in rows if str(row.get("category") or "") == category
        ]
        by_category[category] = {
            "evaluated_tasks": len(category_rows),
            "planner_step_ordered_sequence_recall": _mean(
                [
                    1.0 if row["planner_step_ordered_sequence_recalled"] else 0.0
                    for row in category_rows
                ]
            ),
            "planner_step_ordered_step_coverage_mean": _mean(
                [
                    float(row["planner_step_ordered_step_coverage"])
                    for row in category_rows
                ]
            ),
        }
    summary["by_category"] = by_category

    return {"summary": summary, "rows": rows}


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value) if isinstance(value, list | dict) else value
                    for key, value in row.items()
                }
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--labels-jsonl", type=Path, default=DEFAULT_LABELS)
    parser.add_argument(
        "--predictions-json",
        type=Path,
        required=True,
        help=(
            "JSON or JSONL offline planner-step predictions. Rows must provide "
            "task_id plus planner_step_tool_ids/step_tool_ids or plan.dag.steps."
        ),
    )
    parser.add_argument("--mode", type=str, default=None)
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-csv", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = evaluate(
        labels_jsonl=args.labels_jsonl,
        predictions_json=args.predictions_json,
        mode=args.mode,
        max_tasks=args.max_tasks,
    )
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    if args.out_csv:
        _write_csv(args.out_csv, payload["rows"])
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
