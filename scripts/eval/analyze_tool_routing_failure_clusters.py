#!/usr/bin/env python3
"""Analyze absolute tool-routing recall ceilings and failure clusters.

This is an instrumentation script only. It reads exact-label rows and an
existing prediction artifact, then classifies misses without changing routing
behavior.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

DEFAULT_LABELS = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "microtooling_exact_labels.manual_curated.v2.labels.jsonl"
)
DEFAULT_OUTPUT_BASE = Path("/tmp/br_tool_routing_failure_clusters")
DEFAULT_PREDICTION_GLOBS = (
    "/tmp/br_planner_family_routing_ab/*/predictions.jsonl",
    "/tmp/br-family-ab*/predictions.json",
    "/tmp/br-tool-routing-eval*/predictions.json",
    "/tmp/routing-review-family-ab*/predictions.json",
    str(
        ROOT
        / "benchmarks"
        / "tool_routing_validation"
        / "family_card_ab"
        / "runs"
        / "*"
        / "predictions.json"
    ),
)

BUCKET_PRIORITIES: dict[str, tuple[int, str]] = {
    "hit": (99, "No remediation needed for top-1 exact recall."),
    "missing_exact_label": (
        5,
        "Add exact expected or acceptable tool IDs before using this row for exact recall.",
    ),
    "invalid_label_expected_tool_not_exposed": (
        10,
        "Audit label IDs against the exposed tool catalog; relabel spec-only IDs "
        "or expose intended tools.",
    ),
    "invalid_label_expected_family_not_exposed": (
        15,
        "Audit expected_family_ids against the loaded tool family registry.",
    ),
    "missing_prediction": (
        20,
        "Regenerate the prediction artifact or fix task-id mismatches.",
    ),
    "empty_candidates": (
        25,
        "Inspect candidate generation; the artifact returned no ranked tools for this task.",
    ),
    "retriever_candidate_absent": (
        30,
        "Expected valid tools were not present in the provided ranked candidates; "
        "inspect exposure, aliases, family cards, and filters.",
    ),
    "family_miss": (
        35,
        "Expected family was missed; inspect family selection and modality/category filtering.",
    ),
    "family_correct_tool_wrong": (
        40,
        "Expected family was retrieved but the wrong tool was ranked first; "
        "inspect within-family ranking and aliases.",
    ),
    "retriever_rank_miss": (
        45,
        "A valid expected tool appeared below rank 1; inspect scoring and tie-breaking.",
    ),
    "no_family_labels_tool_miss": (
        50,
        "Tool miss has no expected family labels; add family labels before deeper "
        "family-level diagnosis.",
    ),
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        raw = value
    else:
        raw = str(value).replace(";", ",").split(",")
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _prediction_rows_from_json(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if not isinstance(data, Mapping):
        return []
    candidates = (
        data.get("predictions"),
        data.get("rows"),
        data.get("results"),
        (
            ((data.get("tracks") or {}).get("tools") or {}).get("results")
            if isinstance(data.get("tracks"), Mapping)
            else None
        ),
        (
            (data.get("baseline") or {}).get("results")
            if isinstance(data.get("baseline"), Mapping)
            else None
        ),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, Mapping)]
    return []


def _load_predictions(path: Path, *, mode: str | None) -> dict[str, dict[str, Any]]:
    if path.suffix == ".jsonl":
        rows = _load_jsonl(path)
    else:
        rows = _prediction_rows_from_json(json.loads(path.read_text(encoding="utf-8")))

    out: dict[str, dict[str, Any]] = {}
    seen_modes = {str(row.get("mode") or "").strip() for row in rows if row.get("mode")}
    selected_mode = mode
    if selected_mode and selected_mode.lower() == "auto":
        selected_mode = "cards" if "cards" in seen_modes else None

    for row in rows:
        row_mode = str(row.get("mode") or "").strip()
        if selected_mode and row_mode and row_mode != selected_mode:
            continue
        task_id = str(row.get("task_id") or row.get("id") or "").strip()
        if not task_id:
            continue
        ranked = _as_list(
            row.get("top_tool_ids")
            or row.get("predicted_tool_ids")
            or row.get("predicted_top5_valid")
            or row.get("tool_ids")
        )
        selected = str(row.get("selected_tool_id") or "").strip()
        if selected and (not ranked or selected != ranked[0]):
            ranked = [selected] + [tool_id for tool_id in ranked if tool_id != selected]
        out[task_id] = {
            "task_id": task_id,
            "mode": row_mode or None,
            "ranked_tool_ids": ranked,
            "kg_families": _as_list(row.get("kg_families")),
            "candidate_count": row.get("candidate_count"),
            "raw": dict(row),
        }
    return out


def _load_labels(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path)


def _load_catalog_tool_ids() -> set[str]:
    from brain_researcher.services.agent.planner.catalog_loader import (
        get_capability_index,
    )

    return {
        str(tool_id) for tool_id in get_capability_index(include_local_first=True).by_id
    }


def _load_family_maps() -> tuple[set[str], dict[str, str]]:
    from brain_researcher.services.agent.tool_router import load_tool_families

    families = load_tool_families()
    known_family_ids = {str(family_id) for family_id in families}
    tool_to_family: dict[str, str] = {}
    for family in families.values():
        for tool_id in family.ops.values():
            if tool_id:
                tool_to_family.setdefault(str(tool_id), str(family.id))
    return known_family_ids, tool_to_family


def _rank_of_any(ranked: Sequence[str], truth: set[str]) -> int | None:
    for idx, tool_id in enumerate(ranked, start=1):
        if tool_id in truth:
            return idx
    return None


def _bucket_for_row(
    *,
    has_truth: bool,
    invalid_tool_ids: Sequence[str],
    invalid_family_ids: Sequence[str],
    has_prediction: bool,
    ranked_tool_ids: Sequence[str],
    top1_hit: bool,
    candidate_rank: int | None,
    expected_family_ids: Sequence[str],
    top1_family_hit: bool,
) -> str:
    if not has_truth:
        return "missing_exact_label"
    if invalid_tool_ids:
        return "invalid_label_expected_tool_not_exposed"
    if invalid_family_ids:
        return "invalid_label_expected_family_not_exposed"
    if top1_hit:
        return "hit"
    if not has_prediction:
        return "missing_prediction"
    if not ranked_tool_ids:
        return "empty_candidates"
    if candidate_rank is None:
        return "retriever_candidate_absent"
    if expected_family_ids and not top1_family_hit:
        return "family_miss"
    if expected_family_ids and top1_family_hit:
        return "family_correct_tool_wrong"
    if candidate_rank > 1:
        return "retriever_rank_miss"
    return "no_family_labels_tool_miss"


def _add_cluster(
    clusters: dict[str, dict[str, Any]],
    key: str,
    row: Mapping[str, Any],
) -> None:
    cluster = clusters.setdefault(
        key,
        {
            "cluster": key,
            "task_count": 0,
            "top1_hits": 0,
            "provided_candidate_hits": 0,
            "invalid_label_count": 0,
            "missing_prediction_count": 0,
            "empty_candidate_count": 0,
            "bucket_counts": Counter(),
            "example_task_ids": [],
        },
    )
    cluster["task_count"] += 1
    cluster["top1_hits"] += int(bool(row.get("top1_hit")))
    cluster["provided_candidate_hits"] += int(row.get("candidate_rank") is not None)
    cluster["invalid_label_count"] += int(
        bool(row.get("invalid_tool_ids") or row.get("invalid_family_ids"))
    )
    cluster["missing_prediction_count"] += int(
        row.get("failure_bucket") == "missing_prediction"
    )
    cluster["empty_candidate_count"] += int(
        row.get("failure_bucket") == "empty_candidates"
    )
    cluster["bucket_counts"][str(row.get("failure_bucket"))] += 1
    if len(cluster["example_task_ids"]) < 5:
        cluster["example_task_ids"].append(row.get("task_id"))


def _finalize_clusters(
    clusters: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster in clusters.values():
        task_count = int(cluster["task_count"])
        out = dict(cluster)
        out["top1_recall"] = (
            cluster["top1_hits"] / float(task_count) if task_count else None
        )
        out["provided_candidate_availability_rate"] = (
            cluster["provided_candidate_hits"] / float(task_count)
            if task_count
            else None
        )
        out["bucket_counts"] = dict(cluster["bucket_counts"])
        rows.append(out)
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("task_count") or 0),
            str(row.get("cluster") or ""),
        ),
    )


def _counter_rows(
    counter: Counter[tuple[str, str]],
    examples: Mapping[tuple[str, str], list[str]],
    *,
    first_name: str,
    second_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (first, second), count in counter.most_common(limit):
        rows.append(
            {
                first_name: first,
                second_name: second,
                "count": count,
                "example_task_ids": examples.get((first, second), [])[:5],
            }
        )
    return rows


def analyze(
    *,
    labels_jsonl: Path,
    predictions_path: Path,
    mode: str | None = "auto",
    top_k: int = 10,
    catalog_tool_ids: set[str] | None = None,
    known_family_ids: set[str] | None = None,
    tool_to_family: dict[str, str] | None = None,
    top_limit: int = 25,
) -> dict[str, Any]:
    labels = _load_labels(labels_jsonl)
    predictions = _load_predictions(predictions_path, mode=mode)
    catalog_tool_ids = (
        catalog_tool_ids if catalog_tool_ids is not None else _load_catalog_tool_ids()
    )
    if known_family_ids is None or tool_to_family is None:
        loaded_family_ids, loaded_tool_to_family = _load_family_maps()
        known_family_ids = (
            known_family_ids if known_family_ids is not None else loaded_family_ids
        )
        tool_to_family = (
            tool_to_family if tool_to_family is not None else loaded_tool_to_family
        )

    rows: list[dict[str, Any]] = []
    category_clusters: dict[str, dict[str, Any]] = {}
    family_clusters: dict[str, dict[str, Any]] = {}
    category_family_clusters: dict[str, dict[str, Any]] = {}
    missing_expected_tools: dict[str, dict[str, Any]] = {}
    candidate_absent_expected_tools: dict[str, dict[str, Any]] = {}
    tool_confusions: Counter[tuple[str, str]] = Counter()
    tool_confusion_examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    family_confusions: Counter[tuple[str, str]] = Counter()
    family_confusion_examples: dict[tuple[str, str], list[str]] = defaultdict(list)

    for label in labels:
        task_id = str(label.get("task_id") or "").strip()
        exact = (
            label.get("exact_labels")
            if isinstance(label.get("exact_labels"), Mapping)
            else {}
        )
        expected_tool_ids = _as_list(exact.get("expected_tool_ids"))
        acceptable_tool_ids = _as_list(exact.get("acceptable_tool_ids"))
        expected_sequence_tool_ids = _as_list(exact.get("expected_sequence_tool_ids"))
        expected_family_ids = _as_list(exact.get("expected_family_ids"))
        truth = set(expected_tool_ids + acceptable_tool_ids)
        has_truth = bool(truth)
        category = str(label.get("category") or "uncategorized")

        invalid_tool_ids = [
            tool_id
            for tool_id in expected_tool_ids
            + acceptable_tool_ids
            + expected_sequence_tool_ids
            if tool_id not in catalog_tool_ids
        ]
        invalid_family_ids = [
            family_id
            for family_id in expected_family_ids
            if family_id not in known_family_ids
        ]
        for tool_id in invalid_tool_ids:
            entry = missing_expected_tools.setdefault(
                tool_id,
                {
                    "tool_id": tool_id,
                    "count": 0,
                    "categories": Counter(),
                    "example_task_ids": [],
                },
            )
            entry["count"] += 1
            entry["categories"][category] += 1
            if len(entry["example_task_ids"]) < 5:
                entry["example_task_ids"].append(task_id)

        prediction = predictions.get(task_id)
        ranked_tool_ids = list((prediction or {}).get("ranked_tool_ids") or [])[:top_k]
        predicted_family_ids = [
            tool_to_family.get(tool_id) for tool_id in ranked_tool_ids
        ]
        predicted_top1 = ranked_tool_ids[0] if ranked_tool_ids else None
        predicted_top1_family = (
            predicted_family_ids[0] if predicted_family_ids else None
        )
        candidate_rank = _rank_of_any(ranked_tool_ids, truth)
        top1_hit = bool(predicted_top1 and predicted_top1 in truth)
        top1_family_hit = bool(
            predicted_top1_family and predicted_top1_family in set(expected_family_ids)
        )

        if has_truth and prediction is not None and candidate_rank is None:
            for tool_id in sorted(truth):
                entry = candidate_absent_expected_tools.setdefault(
                    tool_id,
                    {
                        "tool_id": tool_id,
                        "count": 0,
                        "categories": Counter(),
                        "example_task_ids": [],
                    },
                )
                entry["count"] += 1
                entry["categories"][category] += 1
                if len(entry["example_task_ids"]) < 5:
                    entry["example_task_ids"].append(task_id)

        failure_bucket = _bucket_for_row(
            has_truth=has_truth,
            invalid_tool_ids=invalid_tool_ids,
            invalid_family_ids=invalid_family_ids,
            has_prediction=prediction is not None,
            ranked_tool_ids=ranked_tool_ids,
            top1_hit=top1_hit,
            candidate_rank=candidate_rank,
            expected_family_ids=expected_family_ids,
            top1_family_hit=top1_family_hit,
        )

        primary_expected_tool = (
            expected_tool_ids[0]
            if expected_tool_ids
            else (acceptable_tool_ids[0] if acceptable_tool_ids else "none")
        )
        primary_expected_family = (
            expected_family_ids[0] if expected_family_ids else "unlabeled_family"
        )
        if failure_bucket not in {
            "hit",
            "missing_exact_label",
            "missing_prediction",
            "empty_candidates",
        }:
            tool_key = (primary_expected_tool, predicted_top1 or "none")
            tool_confusions[tool_key] += 1
            if len(tool_confusion_examples[tool_key]) < 5:
                tool_confusion_examples[tool_key].append(task_id)
            family_key = (
                primary_expected_family,
                predicted_top1_family or "unknown_family",
            )
            family_confusions[family_key] += 1
            if len(family_confusion_examples[family_key]) < 5:
                family_confusion_examples[family_key].append(task_id)

        row = {
            "task_id": task_id,
            "category": category,
            "query": label.get("query"),
            "expected_tool_ids": expected_tool_ids,
            "acceptable_tool_ids": acceptable_tool_ids,
            "expected_sequence_tool_ids": expected_sequence_tool_ids,
            "expected_family_ids": expected_family_ids,
            "invalid_tool_ids": invalid_tool_ids,
            "invalid_family_ids": invalid_family_ids,
            "predicted_tool_ids": ranked_tool_ids,
            "predicted_family_ids": predicted_family_ids,
            "predicted_top1": predicted_top1,
            "predicted_top1_family": predicted_top1_family,
            "top1_hit": top1_hit,
            "candidate_rank": candidate_rank,
            "provided_candidate_hit": candidate_rank is not None,
            "failure_bucket": failure_bucket,
        }
        rows.append(row)

        _add_cluster(category_clusters, category, row)
        for family_id in expected_family_ids or ["unlabeled_family"]:
            _add_cluster(family_clusters, family_id, row)
            _add_cluster(category_family_clusters, f"{category}::{family_id}", row)

    bucket_counts = Counter(str(row["failure_bucket"]) for row in rows)
    valid_exact_rows = [
        row for row in rows if row["expected_tool_ids"] or row["acceptable_tool_ids"]
    ]
    top1_hits = sum(1 for row in valid_exact_rows if row["top1_hit"])
    candidate_hits = sum(
        1 for row in valid_exact_rows if row["candidate_rank"] is not None
    )
    invalid_label_rows = [
        row for row in rows if row["invalid_tool_ids"] or row["invalid_family_ids"]
    ]

    remediation = []
    for bucket, count in bucket_counts.items():
        if bucket == "hit":
            continue
        priority, action = BUCKET_PRIORITIES.get(
            bucket, (90, "Inspect examples manually.")
        )
        examples = [row["task_id"] for row in rows if row["failure_bucket"] == bucket][
            :5
        ]
        remediation.append(
            {
                "bucket": bucket,
                "priority": priority,
                "count": count,
                "share_of_all_tasks": count / float(len(rows)) if rows else None,
                "recommended_action": action,
                "example_task_ids": examples,
            }
        )
    remediation.sort(key=lambda row: (row["priority"], -row["count"], row["bucket"]))

    def finalize_tool_map(
        items: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in items.values():
            row = dict(entry)
            row["categories"] = dict(row["categories"])
            out.append(row)
        return sorted(out, key=lambda row: (-int(row["count"]), row["tool_id"]))[
            :top_limit
        ]

    summary = {
        "labels_jsonl": str(labels_jsonl),
        "predictions_path": str(predictions_path),
        "mode": mode,
        "top_k": top_k,
        "task_count": len(rows),
        "valid_exact_task_count": len(valid_exact_rows),
        "top1_hit_count": top1_hits,
        "top1_recall": (
            top1_hits / float(len(valid_exact_rows)) if valid_exact_rows else None
        ),
        "provided_candidate_hit_count": candidate_hits,
        "provided_candidate_availability_rate": (
            candidate_hits / float(len(valid_exact_rows)) if valid_exact_rows else None
        ),
        "invalid_label_task_count": len(invalid_label_rows),
        "missing_prediction_count": bucket_counts.get("missing_prediction", 0),
        "empty_candidate_count": bucket_counts.get("empty_candidates", 0),
        "bucket_counts": dict(bucket_counts),
        "note": (
            "candidate availability is measured only within the ranked candidates present "
            "in the supplied prediction artifact"
        ),
    }

    return {
        "summary": summary,
        "remediation_buckets": remediation,
        "clusters": {
            "by_category": _finalize_clusters(category_clusters),
            "by_expected_family": _finalize_clusters(family_clusters),
            "by_category_family": _finalize_clusters(category_family_clusters),
        },
        "missing_expected_tools": finalize_tool_map(missing_expected_tools),
        "candidate_absent_expected_tools": finalize_tool_map(
            candidate_absent_expected_tools
        ),
        "top_tool_confusions": _counter_rows(
            tool_confusions,
            tool_confusion_examples,
            first_name="expected_tool_id",
            second_name="predicted_top1",
            limit=top_limit,
        ),
        "top_family_confusions": _counter_rows(
            family_confusions,
            family_confusion_examples,
            first_name="expected_family_id",
            second_name="predicted_top1_family",
            limit=top_limit,
        ),
        "task_failures": [
            row
            for row in sorted(
                rows,
                key=lambda item: (
                    BUCKET_PRIORITIES.get(item["failure_bucket"], (90, ""))[0],
                    item["category"],
                    item["task_id"],
                ),
            )
            if row["failure_bucket"] != "hit"
        ],
        "rows": rows,
    }


def _default_predictions_path() -> Path | None:
    candidates: list[Path] = []
    for pattern in DEFAULT_PREDICTION_GLOBS:
        candidates.extend(
            Path(path) for path in glob.glob(pattern) if Path(path).is_file()
        )
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Tool Routing Failure Clusters",
        "",
        "This report is instrumentation-only and does not change production routing.",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2, sort_keys=True),
        "```",
        "",
        "## Prioritized Remediation",
        "",
        "| Priority | Bucket | Count | Examples | Action |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for row in payload["remediation_buckets"]:
        lines.append(
            "| {priority} | {bucket} | {count} | {examples} | {action} |".format(
                priority=row["priority"],
                bucket=row["bucket"],
                count=row["count"],
                examples=", ".join(row["example_task_ids"]),
                action=row["recommended_action"],
            )
        )
    lines.extend(
        [
            "",
            "## Largest Category Clusters",
            "",
            "| Category | Tasks | Top-1 Recall | Candidate Availability | Buckets |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in payload["clusters"]["by_category"][:20]:
        lines.append(
            "| {cluster} | {task_count} | {recall:.3f} | {avail:.3f} | {buckets} |".format(
                cluster=row["cluster"],
                task_count=row["task_count"],
                recall=row["top1_recall"] or 0.0,
                avail=row["provided_candidate_availability_rate"] or 0.0,
                buckets=json.dumps(row["bucket_counts"], sort_keys=True),
            )
        )
    lines.extend(
        [
            "",
            "## Top Tool Confusions",
            "",
            "| Expected | Predicted Top-1 | Count | Examples |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for row in payload["top_tool_confusions"][:20]:
        lines.append(
            "| {expected_tool_id} | {predicted_top1} | {count} | {examples} |".format(
                expected_tool_id=row["expected_tool_id"],
                predicted_top1=row["predicted_top1"],
                count=row["count"],
                examples=", ".join(row["example_task_ids"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(payload: Mapping[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "failure_clusters.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "task_failures.jsonl", payload["task_failures"])
    _write_markdown(output_dir / "failure_clusters.md", payload)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-jsonl", type=Path, default=DEFAULT_LABELS)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--predictions-json", type=Path)
    group.add_argument("--predictions-jsonl", type=Path)
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        help="Prediction mode to analyze. Use auto to prefer cards when present.",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--top-limit", type=int, default=25)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    predictions_path = args.predictions_json or args.predictions_jsonl
    if predictions_path is None:
        predictions_path = _default_predictions_path()
    if predictions_path is None:
        raise SystemExit(
            "No predictions artifact found. Pass --predictions-json or --predictions-jsonl."
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_OUTPUT_BASE / stamp
    payload = analyze(
        labels_jsonl=args.labels_jsonl,
        predictions_path=predictions_path,
        mode=args.mode,
        top_k=args.top_k,
        top_limit=args.top_limit,
    )
    write_outputs(payload, output_dir)
    print(
        json.dumps(
            {**payload["summary"], "output_dir": str(output_dir)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
