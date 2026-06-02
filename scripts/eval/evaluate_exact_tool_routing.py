#!/usr/bin/env python3
"""Evaluate router predictions against curated exact tool/family labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.planner.catalog_loader import get_capability_index
from brain_researcher.services.agent.tool_router import load_tool_families


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_predictions(path: Path, *, mode: str | None) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: Sequence[Any]
    if isinstance(data, list):
        rows = data
    elif isinstance(data, Mapping):
        rows = (
            ((data.get("tracks") or {}).get("tools") or {}).get("results")
            or (data.get("baseline") or {}).get("results")
            or data.get("predictions")
            or []
        )
    else:
        rows = []

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if mode and str(row.get("mode") or "") != mode:
            continue
        task_id = str(row.get("task_id") or "").strip()
        if not task_id:
            continue
        tools = _as_list(
            row.get("predicted_top5_valid")
            or row.get("top_tool_ids")
            or row.get("predicted_tool_ids")
        )
        out[task_id] = {
            "tool_ids": tools,
            "latency_ms": _float_or_none(
                row.get("latency_ms")
                or row.get("wall_time_ms")
                or row.get("duration_ms")
            ),
        }
    return out


def _tool_to_family_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for family in load_tool_families().values():
        for tool_id in family.ops.values():
            if tool_id and tool_id not in out:
                out[str(tool_id)] = family.id
    return out


def _sequence_hit(predicted: Sequence[str], expected_sequence: Sequence[str], k: int) -> bool:
    if not expected_sequence:
        return False
    cursor = 0
    for tool_id in predicted[:k]:
        if cursor < len(expected_sequence) and tool_id == expected_sequence[cursor]:
            cursor += 1
    return cursor == len(expected_sequence)


def evaluate(
    *,
    labels_jsonl: Path,
    predictions_json: Path,
    mode: str | None,
    k_values: Sequence[int],
) -> dict[str, Any]:
    labels = _load_jsonl(labels_jsonl)
    predictions = _load_predictions(predictions_json, mode=mode)
    catalog_tool_ids = set(get_capability_index().by_id)
    family_ids = set(load_tool_families())
    tool_to_family = _tool_to_family_map()

    rows: list[dict[str, Any]] = []
    invalid_labels: list[dict[str, str]] = []
    skipped_missing_labels = 0
    skipped_missing_predictions = 0

    for label_row in labels:
        task_id = str(label_row.get("task_id") or "").strip()
        exact = label_row.get("exact_labels") or {}
        expected_tools = _as_list(exact.get("expected_tool_ids"))
        acceptable_tools = _as_list(exact.get("acceptable_tool_ids"))
        expected_families = _as_list(exact.get("expected_family_ids"))
        expected_sequence = _as_list(exact.get("expected_sequence_tool_ids"))
        if not (expected_tools or acceptable_tools or expected_families or expected_sequence):
            skipped_missing_labels += 1
            continue

        for tool_id in expected_tools + acceptable_tools + expected_sequence:
            if tool_id not in catalog_tool_ids:
                invalid_labels.append({"task_id": task_id, "invalid_tool_id": tool_id})
        for family_id in expected_families:
            if family_id not in family_ids:
                invalid_labels.append({"task_id": task_id, "invalid_family_id": family_id})

        prediction = predictions.get(task_id)
        if prediction is None:
            skipped_missing_predictions += 1
            continue
        predicted = _as_list(prediction.get("tool_ids"))
        latency_ms = _float_or_none(prediction.get("latency_ms"))

        valid_tool_truth = set(expected_tools + acceptable_tools)
        predicted_families = [tool_to_family.get(tool_id) for tool_id in predicted]
        row: dict[str, Any] = {
            "task_id": task_id,
            "category": label_row.get("category"),
            "predicted_tool_ids": predicted,
            "predicted_family_ids": predicted_families,
            "expected_tool_ids": expected_tools,
            "acceptable_tool_ids": acceptable_tools,
            "expected_family_ids": expected_families,
            "expected_sequence_tool_ids": expected_sequence,
            "latency_ms": latency_ms,
            "top1_wrong_tool": bool(valid_tool_truth)
            and (not predicted or predicted[0] not in valid_tool_truth),
        }
        for k in k_values:
            row[f"tool_recall_at_{k}"] = bool(valid_tool_truth) and any(
                tool_id in valid_tool_truth for tool_id in predicted[:k]
            )
            row[f"family_recall_at_{k}"] = bool(expected_families) and any(
                family_id in set(expected_families)
                for family_id in predicted_families[:k]
                if family_id
            )
            row[f"sequence_recall_at_{k}"] = _sequence_hit(predicted, expected_sequence, k)
        rows.append(row)

    summary: dict[str, Any] = {
        "mode": mode,
        "evaluated_tasks": len(rows),
        "skipped_missing_exact_labels": skipped_missing_labels,
        "skipped_missing_predictions": skipped_missing_predictions,
        "invalid_label_count": len(invalid_labels),
    }
    for k in k_values:
        denom = len(rows) or 1
        summary[f"tool_recall_at_{k}"] = (
            sum(1 for row in rows if row[f"tool_recall_at_{k}"]) / denom
            if rows
            else None
        )
        family_rows = [row for row in rows if row.get("expected_family_ids")]
        summary[f"family_recall_at_{k}"] = (
            sum(1 for row in family_rows if row[f"family_recall_at_{k}"])
            / float(len(family_rows))
            if family_rows
            else None
        )
        sequence_rows = [row for row in rows if row.get("expected_sequence_tool_ids")]
        summary[f"sequence_recall_at_{k}"] = (
            sum(1 for row in sequence_rows if row[f"sequence_recall_at_{k}"])
            / float(len(sequence_rows))
            if sequence_rows
            else None
        )
    summary["wrong_tool_top1_rate"] = (
        sum(1 for row in rows if row["top1_wrong_tool"]) / float(len(rows))
        if rows
        else None
    )
    latencies = sorted(
        float(row["latency_ms"])
        for row in rows
        if row.get("latency_ms") is not None
    )
    summary["latency_count"] = len(latencies)
    summary["latency_mean_ms"] = (
        sum(latencies) / float(len(latencies)) if latencies else None
    )
    summary["latency_median_ms"] = _quantile(latencies, 0.5)
    summary["latency_p95_ms"] = _quantile(latencies, 0.95)
    return {"summary": summary, "rows": rows, "invalid_labels": invalid_labels}


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


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


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.autocurated.v1.labels.jsonl",
    )
    parser.add_argument("--predictions-json", type=Path, required=True)
    parser.add_argument("--mode", type=str, default=None)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path, default=None)
    parser.add_argument("--k", type=int, action="append", default=[1, 3, 5])
    args = parser.parse_args()

    payload = evaluate(
        labels_jsonl=args.labels_jsonl,
        predictions_json=args.predictions_json,
        mode=args.mode,
        k_values=sorted(set(args.k)),
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_csv:
        _write_csv(args.out_csv, payload["rows"])
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
