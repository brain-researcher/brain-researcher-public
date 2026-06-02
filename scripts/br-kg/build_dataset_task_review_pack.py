#!/usr/bin/env python3
"""Build dataset-context review pack for remaining unmatched task tokens."""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from brain_researcher.core.datasets.catalog import load_catalog
from brain_researcher.services.br_kg.etl.dataset_task_linker import (
    load_task_mapping_config,
    normalize_task,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CATALOGS = [
    Path("configs/datasets/catalog.v1.jsonl"),
    Path("configs/datasets/catalog_manual.jsonl"),
    Path("configs/datasets/catalog_openneuro.jsonl"),
]
DEFAULT_TASK_MAPPING = Path("configs/legacy/task_mapping.yaml")
DEFAULT_UNMATCHED = Path("/tmp/dataset_task_unmatched.tsv")
DEFAULT_OUTPUT_DIR = Path("artifacts/dataset_task_review")


def _load_unmatched(path: Path) -> tuple[dict[str, int], dict[str, str]]:
    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Unmatched report not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        header = handle.readline()
        if not header:
            return counts, examples
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            norm, count, example = parts
            if not norm:
                continue
            try:
                counts[norm] = int(count)
            except ValueError:
                counts[norm] = 0
            if example:
                examples[norm] = example
    return counts, examples


def _task_json_summaries(dataset_root: Path, max_files: int) -> list[str]:
    summaries: list[str] = []
    if not dataset_root.exists():
        return summaries
    try:
        for path in dataset_root.rglob("task-*.json"):
            if len(summaries) >= max_files:
                break
            label = path.name
            task_name = None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    task_name = payload.get("TaskName") or payload.get("task_name")
            except Exception:
                task_name = None
            if task_name:
                summaries.append(f"{label}:{task_name}")
            else:
                summaries.append(label)
    except Exception:
        return summaries
    return sorted(set(summaries))


def _summarize_tasks(tasks: Iterable[str], *, exclude_norm: str, max_items: int, config) -> str:
    other_tasks: list[str] = []
    for task in tasks:
        norm = normalize_task(task, config)
        if norm == exclude_norm:
            continue
        other_tasks.append(task)
    if not other_tasks:
        return ""
    if len(other_tasks) <= max_items:
        return "|".join(other_tasks)
    truncated = other_tasks[:max_items]
    return "|".join(truncated) + f"|...(+{len(other_tasks) - max_items})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dataset task review pack")
    parser.add_argument(
        "--unmatched",
        type=Path,
        default=DEFAULT_UNMATCHED,
        help="Path to unmatched TSV report",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for review pack artifacts",
    )
    parser.add_argument(
        "--catalog",
        action="append",
        default=None,
        help="Path to dataset catalog JSONL (repeatable)",
    )
    parser.add_argument(
        "--task-mapping",
        type=Path,
        default=DEFAULT_TASK_MAPPING,
        help="Path to task_mapping.yaml",
    )
    parser.add_argument(
        "--ignore-blacklist",
        action="store_true",
        help="Ignore task blacklist when normalizing",
    )
    parser.add_argument(
        "--max-other-tasks",
        type=int,
        default=15,
        help="Max number of other tasks to include per dataset row",
    )
    parser.add_argument(
        "--max-task-files",
        type=int,
        default=20,
        help="Max task-*.json files to include per dataset",
    )
    parser.add_argument(
        "--scan-task-json",
        action="store_true",
        help="Scan dataset roots for task-*.json metadata",
    )
    args = parser.parse_args()

    unmatched_counts, unmatched_examples = _load_unmatched(args.unmatched)
    if not unmatched_counts:
        raise SystemExit("No unmatched tokens found; nothing to review.")
    unmatched_set = set(unmatched_counts.keys())

    catalogs = [Path(p) for p in (args.catalog or [])] or DEFAULT_CATALOGS
    config = load_task_mapping_config(
        args.task_mapping,
        enable_fuzzy=False,
        ignore_blacklist=args.ignore_blacklist,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    review_pack_path = args.out_dir / "review_pack.tsv"
    top_tokens_path = args.out_dir / "top_tokens.tsv"

    dataset_token_map: dict[tuple[str, str], dict[str, object]] = {}
    token_dataset_sets: dict[str, set[str]] = defaultdict(set)

    for catalog_path in catalogs:
        if not catalog_path.exists():
            logger.warning("Catalog not found: %s", catalog_path)
            continue
        records = load_catalog(catalog_path)
        logger.info("Loaded %s records from %s", len(records), catalog_path)
        for rec in records:
            if not rec.tasks:
                continue
            dataset_id = rec.dataset_id
            dataset_name = rec.name
            source_repo = rec.source_repo
            created_from = rec.created_from or ""
            dataset_root = Path(created_from).parent if created_from else None

            matched_norms = []
            for raw_task in rec.tasks:
                norm = normalize_task(raw_task, config)
                if norm in unmatched_set:
                    matched_norms.append((norm, raw_task))

            if not matched_norms:
                continue

            task_json_summary = ""
            if args.scan_task_json and dataset_root is not None:
                summaries = _task_json_summaries(dataset_root, args.max_task_files)
                if summaries:
                    task_json_summary = "|".join(summaries)

            for norm, raw_task in matched_norms:
                token_dataset_sets[norm].add(dataset_id)
                key = (dataset_id, norm)
                entry = dataset_token_map.setdefault(
                    key,
                    {
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "source_repo": source_repo,
                        "normalized_task": norm,
                        "raw_examples": set(),
                        "count": 0,
                        "other_tasks": "",
                        "task_json": task_json_summary,
                    },
                )
                entry["raw_examples"].add(raw_task)
                entry["count"] += 1
                entry["other_tasks"] = _summarize_tasks(
                    rec.tasks,
                    exclude_norm=norm,
                    max_items=args.max_other_tasks,
                    config=config,
                )

    review_lines = [
        "\t".join(
            [
                "dataset_id",
                "dataset_name",
                "source_repo",
                "normalized_task",
                "raw_examples",
                "count_in_dataset",
                "total_count",
                "other_tasks_in_dataset",
                "task_json_summary",
            ]
        )
    ]
    for (dataset_id, norm), entry in sorted(dataset_token_map.items()):
        raw_examples = sorted(entry["raw_examples"])[:3]
        total_count = unmatched_counts.get(norm, 0)
        review_lines.append(
            "\t".join(
                [
                    dataset_id,
                    str(entry["dataset_name"] or ""),
                    str(entry["source_repo"] or ""),
                    norm,
                    "|".join(raw_examples),
                    str(entry["count"]),
                    str(total_count),
                    entry["other_tasks"],
                    entry["task_json"],
                ]
            )
        )

    review_pack_path.write_text("\n".join(review_lines), encoding="utf-8")
    logger.info("Wrote review pack to %s", review_pack_path)

    top_lines = ["normalized_task\ttotal_count\tn_datasets\texample_raw_task"]
    for norm, total in sorted(unmatched_counts.items(), key=lambda kv: kv[1], reverse=True):
        top_lines.append(
            "\t".join(
                [
                    norm,
                    str(total),
                    str(len(token_dataset_sets.get(norm, set()))),
                    unmatched_examples.get(norm, ""),
                ]
            )
        )
    top_tokens_path.write_text("\n".join(top_lines), encoding="utf-8")
    logger.info("Wrote top tokens report to %s", top_tokens_path)


if __name__ == "__main__":
    main()
