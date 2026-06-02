#!/usr/bin/env python3
"""Build a dataset-context review pack for BIDS task labels on missing fMRI datasets.

This script targets the specific gap where fMRI/BOLD datasets have no HAS_TASK/USES_TASK
edges and their BIDS `task-<label>` values cannot be mapped to existing Task nodes.

Inputs:
  - An unmatched TSV report (normalized_task, count, example_raw_task) produced by
    create_dataset_task_relationships.py with --report-include-bids-unmatched.

Outputs:
  - review_pack.tsv: per-dataset context rows for tokens found via BIDS scan
  - top_tokens.tsv: aggregate token frequency across missing fMRI datasets
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from brain_researcher.services.br_kg.etl.dataset_task_linker import (
    load_task_mapping_config,
    normalize_task,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_TASK_MAPPING = Path("configs/legacy/task_mapping.yaml")
DEFAULT_UNMATCHED = Path("/tmp/bids_task_unmatched.tsv")
DEFAULT_OUT_DIR = Path("artifacts/dataset_task_review_bids_missing_fmri")

_TASK_LABEL_RE = re.compile(r"task-([^_\\.]+)", flags=re.IGNORECASE)


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


def _iter_missing_fmri_datasets(db) -> list[dict[str, object]]:
    cypher = """
    MATCH (d:Dataset)
    WHERE (
        any(m IN coalesce(d.modalities, []) WHERE
            toLower(m) CONTAINS 'fmri' OR toLower(m) = 'bold' OR toLower(m) = 'func'
        )
        OR any(a IN coalesce(d.acquisitions, []) WHERE toLower(a) = 'bold')
    )
    AND NOT (d)-[:HAS_TASK|USES_TASK]->()
    RETURN d.id AS id, d.name AS name, d.created_from AS created_from
    ORDER BY d.id
    """
    return [dict(row) for row in db.execute_query(cypher)]


def _scan_bids_task_labels(dataset_root: Path) -> Counter[str]:
    counter: Counter[str] = Counter()
    if not dataset_root.exists():
        return counter

    skip_dirs = {".git", ".datalad", ".github", "__pycache__", "derivatives"}
    for dirpath, dirnames, filenames in os.walk(dataset_root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for name in filenames:
            lower = name.lower()
            if "task-" not in lower:
                continue
            if not (
                lower.endswith(".nii")
                or lower.endswith(".nii.gz")
                or lower.endswith(".json")
                or lower.endswith(".tsv")
                or lower.endswith(".tsv.gz")
            ):
                continue
            match = _TASK_LABEL_RE.search(name)
            if not match:
                continue
            label = match.group(1).strip()
            if label:
                counter[label] += 1
    return counter


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


def _summarize_labels(labels: list[str], *, exclude: str, max_items: int) -> str:
    others = [label for label in labels if label != exclude]
    if not others:
        return ""
    if len(others) <= max_items:
        return "|".join(sorted(others))
    truncated = sorted(others)[:max_items]
    return "|".join(truncated) + f"|...(+{len(others) - max_items})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BIDS-missing-fMRI task review pack")
    parser.add_argument(
        "--unmatched",
        type=Path,
        default=DEFAULT_UNMATCHED,
        help="Path to unmatched TSV report from create_dataset_task_relationships.py",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for review pack artifacts",
    )
    parser.add_argument(
        "--task-mapping",
        type=Path,
        default=DEFAULT_TASK_MAPPING,
        help="Path to task_mapping.yaml (used for normalization)",
    )
    parser.add_argument(
        "--ignore-blacklist",
        action="store_true",
        help="Ignore task blacklist when normalizing tokens for review",
    )
    parser.add_argument(
        "--max-other-labels",
        type=int,
        default=15,
        help="Max number of other BIDS task labels to include per dataset row",
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

    config = load_task_mapping_config(
        args.task_mapping,
        enable_fuzzy=False,
        ignore_blacklist=args.ignore_blacklist,
    )

    db = require_neo4j_db(preload_cache=False)
    try:
        datasets = _iter_missing_fmri_datasets(db)
    finally:
        db.close()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    review_pack_path = args.out_dir / "review_pack.tsv"
    top_tokens_path = args.out_dir / "top_tokens.tsv"

    dataset_token_map: dict[tuple[str, str], dict[str, object]] = {}
    token_dataset_sets: dict[str, set[str]] = defaultdict(set)
    token_raw_examples: dict[str, str] = {}

    for row in datasets:
        dataset_id = str(row.get("id") or "")
        dataset_name = str(row.get("name") or "")
        created_from = str(row.get("created_from") or "")
        if not dataset_id or not created_from:
            continue
        dataset_root = Path(created_from).parent
        label_counts = _scan_bids_task_labels(dataset_root)
        if not label_counts:
            continue
        labels_sorted = sorted(label_counts.keys())

        task_json_summary = ""
        if args.scan_task_json:
            summaries = _task_json_summaries(dataset_root, args.max_task_files)
            if summaries:
                task_json_summary = "|".join(summaries)

        for raw_label, count in label_counts.items():
            normalized = normalize_task(raw_label, config)
            if not normalized or normalized not in unmatched_set:
                continue
            token_dataset_sets[normalized].add(dataset_id)
            token_raw_examples.setdefault(normalized, raw_label)

            key = (dataset_id, normalized)
            entry = dataset_token_map.setdefault(
                key,
                {
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                    "source_repo": "openneuro" if "openneuro" in dataset_id.lower() else "bids",
                    "normalized_task": normalized,
                    "raw_examples": set(),
                    "count": 0,
                    "other_tasks": "",
                    "task_json": task_json_summary,
                },
            )
            entry["raw_examples"].add(raw_label)
            entry["count"] += int(count)
            entry["other_tasks"] = _summarize_labels(
                labels_sorted,
                exclude=raw_label,
                max_items=args.max_other_labels,
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
                    token_raw_examples.get(norm, unmatched_examples.get(norm, "")),
                ]
            )
        )
    top_tokens_path.write_text("\n".join(top_lines), encoding="utf-8")
    logger.info("Wrote top tokens report to %s", top_tokens_path)


if __name__ == "__main__":
    main()
