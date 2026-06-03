#!/usr/bin/env python3
"""Audit sequence labels used by exact tool-routing evaluation.

This is an audit/instrumentation script only. It does not change router
behavior or the main evaluator.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.planner.catalog_loader import get_capability_index

DEFAULT_K_VALUES = (1, 3)
EXACT_LABEL_FIELDS = (
    "expected_tool_ids",
    "acceptable_tool_ids",
    "expected_family_ids",
    "expected_sequence_tool_ids",
)


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


def _catalog_tool_ids() -> set[str]:
    return set(get_capability_index().by_id)


def ordered_subsequence_at_k(
    predicted_tool_ids: Sequence[str],
    expected_sequence_tool_ids: Sequence[str],
    k: int,
) -> bool:
    """Return whether the expected sequence appears in order within top-k."""
    if not expected_sequence_tool_ids:
        return False
    return ordered_step_match_count_at_k(
        predicted_tool_ids, expected_sequence_tool_ids, k
    ) == len(expected_sequence_tool_ids)


def ordered_step_match_count_at_k(
    predicted_tool_ids: Sequence[str],
    expected_sequence_tool_ids: Sequence[str],
    k: int,
) -> int:
    """Count ordered expected steps matched by the flat ranked top-k list."""
    cursor = 0
    for tool_id in predicted_tool_ids[:k]:
        if (
            cursor < len(expected_sequence_tool_ids)
            and tool_id == expected_sequence_tool_ids[cursor]
        ):
            cursor += 1
    return cursor


def ordered_step_coverage_at_k(
    predicted_tool_ids: Sequence[str],
    expected_sequence_tool_ids: Sequence[str],
    k: int,
) -> float | None:
    """Return the fraction of ordered expected steps matched within top-k."""
    if not expected_sequence_tool_ids:
        return None
    return ordered_step_match_count_at_k(
        predicted_tool_ids,
        expected_sequence_tool_ids,
        k,
    ) / float(len(expected_sequence_tool_ids))


def _exact_labels(row: Mapping[str, Any]) -> dict[str, list[str]]:
    exact = (
        row.get("exact_labels") if isinstance(row.get("exact_labels"), Mapping) else {}
    )
    return {field: _as_list(exact.get(field)) for field in EXACT_LABEL_FIELDS}


def _sequence_conflict_reasons(labels: Mapping[str, list[str]]) -> list[str]:
    expected = labels["expected_tool_ids"]
    sequence = labels["expected_sequence_tool_ids"]
    if not sequence:
        return []

    reasons: list[str] = []
    missing_from_expected = [
        tool_id for tool_id in sequence if tool_id not in set(expected)
    ]
    expected_outside_sequence = [
        tool_id for tool_id in expected if tool_id not in set(sequence)
    ]
    if missing_from_expected:
        reasons.append("sequence_tool_missing_from_expected_tool_ids")
    if expected and expected_outside_sequence:
        reasons.append("expected_tool_ids_include_non_sequence_tools")
    if expected and not missing_from_expected and sequence != expected[: len(sequence)]:
        reasons.append("sequence_order_differs_from_expected_tool_ids")
    return reasons


def _metric_impossible_reasons(sequence: Sequence[str], k: int) -> list[str]:
    if not sequence:
        return []
    reasons: list[str] = []
    if len(sequence) > k:
        reasons.append(f"sequence_length_gt_top{k}")
    duplicate_ids = sorted(
        tool_id for tool_id, count in Counter(sequence).items() if count > 1
    )
    if duplicate_ids:
        reasons.append("duplicate_sequence_tool_ids_assuming_unique_ranked_predictions")
    return reasons


def _row_stub(
    row: Mapping[str, Any], labels: Mapping[str, list[str]]
) -> dict[str, Any]:
    return {
        "line_number": row.get("_line_number"),
        "task_id": row.get("task_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "expected_tool_ids": labels["expected_tool_ids"],
        "expected_sequence_tool_ids": labels["expected_sequence_tool_ids"],
    }


def analyze_sequence_labels(
    rows: Sequence[Mapping[str, Any]],
    *,
    catalog_tool_ids: set[str] | None = None,
    k_values: Sequence[int] = DEFAULT_K_VALUES,
    suspect_limit: int = 12,
) -> dict[str, Any]:
    """Return machine-readable sequence-label audit results."""
    catalog_tool_ids = (
        catalog_tool_ids if catalog_tool_ids is not None else _catalog_tool_ids()
    )
    k_values = tuple(sorted(set(k_values)))

    sequence_rows: list[tuple[Mapping[str, Any], dict[str, list[str]]]] = []
    invalid_sequence_tool_ids: list[dict[str, Any]] = []
    expected_sequence_conflicts: list[dict[str, Any]] = []
    metric_impossible_cases: dict[str, list[dict[str, Any]]] = {
        f"top_{k}": [] for k in k_values
    }
    suspect_rows: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    sequence_length_counts: Counter[int] = Counter()
    unique_sequence_tools: Counter[str] = Counter()

    for row in rows:
        labels = _exact_labels(row)
        sequence = labels["expected_sequence_tool_ids"]
        if not sequence:
            continue

        sequence_rows.append((row, labels))
        category_counts[str(row.get("category") or "")] += 1
        sequence_length_counts[len(sequence)] += 1
        unique_sequence_tools.update(sequence)

        reasons: list[str] = []
        invalid_ids = [
            tool_id for tool_id in sequence if tool_id not in catalog_tool_ids
        ]
        for tool_id in invalid_ids:
            invalid_sequence_tool_ids.append(
                {
                    "line_number": row.get("_line_number"),
                    "task_id": row.get("task_id"),
                    "category": row.get("category"),
                    "invalid_tool_id": tool_id,
                }
            )
        if invalid_ids:
            reasons.append("invalid_sequence_tool_id")

        conflict_reasons = _sequence_conflict_reasons(labels)
        if conflict_reasons:
            conflict = _row_stub(row, labels)
            conflict["reasons"] = conflict_reasons
            conflict["sequence_ids_missing_from_expected_tool_ids"] = [
                tool_id
                for tool_id in sequence
                if tool_id not in set(labels["expected_tool_ids"])
            ]
            conflict["expected_tool_ids_not_in_sequence"] = [
                tool_id
                for tool_id in labels["expected_tool_ids"]
                if tool_id not in set(sequence)
            ]
            expected_sequence_conflicts.append(conflict)
            reasons.extend(conflict_reasons)

        for k in k_values:
            impossible_reasons = _metric_impossible_reasons(sequence, k)
            if impossible_reasons:
                impossible = _row_stub(row, labels)
                impossible["reasons"] = impossible_reasons
                metric_impossible_cases[f"top_{k}"].append(impossible)
                reasons.extend(f"top_{k}:{reason}" for reason in impossible_reasons)

        if reasons:
            suspect = _row_stub(row, labels)
            suspect["reasons"] = sorted(set(reasons))
            suspect_rows.append(suspect)

    lengths = [len(labels["expected_sequence_tool_ids"]) for _, labels in sequence_rows]
    sequence_count = len(sequence_rows)
    summary = {
        "total_rows": len(rows),
        "sequence_rows": sequence_count,
        "sequence_row_fraction": sequence_count / float(len(rows)) if rows else None,
        "sequence_length_distribution": {
            str(length): count
            for length, count in sorted(sequence_length_counts.items())
        },
        "sequence_length_min": min(lengths) if lengths else None,
        "sequence_length_max": max(lengths) if lengths else None,
        "sequence_length_mean": sum(lengths) / float(len(lengths)) if lengths else None,
        "invalid_sequence_tool_id_count": len(invalid_sequence_tool_ids),
        "rows_with_expected_sequence_conflicts": len(expected_sequence_conflicts),
        "unique_sequence_tool_id_count": len(unique_sequence_tools),
        "sequence_rows_by_category": dict(sorted(category_counts.items())),
    }
    for k in k_values:
        cases = metric_impossible_cases[f"top_{k}"]
        summary[f"likely_metric_impossible_top_{k}_count"] = len(cases)
        summary[f"ordered_subsequence_at_{k}_max_possible_from_labels"] = (
            (sequence_count - len(cases)) / float(sequence_count)
            if sequence_count
            else None
        )

    return {
        "summary": summary,
        "invalid_sequence_tool_ids": invalid_sequence_tool_ids,
        "expected_sequence_conflicts": expected_sequence_conflicts,
        "likely_metric_impossible_cases": metric_impossible_cases,
        "representative_suspect_rows": suspect_rows[: max(0, suspect_limit)],
        "top_sequence_tool_ids": [
            {"tool_id": tool_id, "count": count}
            for tool_id, count in unique_sequence_tools.most_common(25)
        ],
    }


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.manual_curated.v2.labels.jsonl",
    )
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument(
        "--k", type=int, action="append", default=list(DEFAULT_K_VALUES)
    )
    parser.add_argument("--suspect-limit", type=int, default=12)
    args = parser.parse_args()

    payload = analyze_sequence_labels(
        _load_jsonl(args.labels_jsonl),
        k_values=args.k,
        suspect_limit=args.suspect_limit,
    )
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
