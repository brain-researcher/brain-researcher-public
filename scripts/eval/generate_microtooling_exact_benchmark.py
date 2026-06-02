#!/usr/bin/env python3
"""Generate a bounded curated MicroTooling exact-label benchmark subset."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EXACT_LABEL_FIELDS = (
    "expected_tool_ids",
    "acceptable_tool_ids",
    "expected_family_ids",
    "expected_sequence_tool_ids",
)
DEFAULT_OUTPUT_SCHEMA_VERSION = "br.tool_routing_exact_labels.curated.v1"
DEFAULT_OUTPUT_CURATION_STATUS = "curated_candidate"
DEFAULT_OUTPUT_LABEL_SOURCE = "deterministic_curated_subset_from_autocurated_seed.v1"
DEFAULT_PER_CATEGORY = 12
DEFAULT_MAX_TASKS = 264
AMBIGUITY_RANK = {"low": 0, "medium": 1, "high": 2}
DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}


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
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _exact_counts(row: Mapping[str, Any]) -> dict[str, int]:
    exact = row.get("exact_labels") or {}
    if not isinstance(exact, Mapping):
        return dict.fromkeys(EXACT_LABEL_FIELDS, 0)
    return {field: len(_as_list(exact.get(field))) for field in EXACT_LABEL_FIELDS}


def _has_exact_labels(row: Mapping[str, Any]) -> bool:
    return any(_exact_counts(row).values())


def _label_complexity(row: Mapping[str, Any]) -> int:
    counts = _exact_counts(row)
    return sum(counts.values())


def _derive_difficulty(row: Mapping[str, Any]) -> str:
    for key in ("difficulty", "difficulty_level"):
        value = str(row.get(key) or "").strip()
        if value:
            return value

    counts = _exact_counts(row)
    expected = counts["expected_tool_ids"]
    acceptable = counts["acceptable_tool_ids"]
    families = counts["expected_family_ids"]
    sequence = counts["expected_sequence_tool_ids"]
    if sequence or expected >= 4 or expected + families >= 5:
        return "hard"
    if expected >= 2 or acceptable >= 4 or families:
        return "medium"
    return "easy"


def _derive_ambiguity(row: Mapping[str, Any]) -> str:
    for key in ("ambiguity", "ambiguity_level"):
        value = str(row.get(key) or "").strip()
        if value:
            return value

    counts = _exact_counts(row)
    expected = counts["expected_tool_ids"]
    acceptable = counts["acceptable_tool_ids"]
    families = counts["expected_family_ids"]
    sequence = counts["expected_sequence_tool_ids"]
    if expected <= 1 and acceptable <= 1 and not families and not sequence:
        return "low"
    if expected <= 2 and acceptable <= 5 and sequence <= 1:
        return "medium"
    return "high"


def _normalize_row(
    row: Mapping[str, Any],
    *,
    output_schema_version: str = DEFAULT_OUTPUT_SCHEMA_VERSION,
    output_curation_status: str | None = None,
    output_label_source: str | None = None,
) -> dict[str, Any]:
    exact = row.get("exact_labels") or {}
    source_curation_status = row.get("curation_status")
    source_label_source = row.get("label_source")
    difficulty = _derive_difficulty(row)
    ambiguity = _derive_ambiguity(row)
    return {
        "schema_version": output_schema_version,
        "source_schema_version": row.get("schema_version"),
        "task_id": row.get("task_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "weak_expected_capabilities": _as_list(row.get("weak_expected_capabilities")),
        "curation_status": output_curation_status or source_curation_status,
        "source_curation_status": source_curation_status,
        "difficulty": difficulty,
        "ambiguity": ambiguity,
        "exact_labels": {
            field: _as_list(exact.get(field)) if isinstance(exact, Mapping) else []
            for field in EXACT_LABEL_FIELDS
        },
        "label_source": output_label_source or source_label_source,
        "source_label_source": source_label_source,
        "selection_metadata": {
            "benchmark_split": "microtooling_curated_exact_v1",
            "label_complexity": _label_complexity(row),
            "selection_reason": [
                "exact_catalog_labels_present",
                "balanced_category_subset",
                f"source_status:{source_curation_status}",
            ],
        },
    }


def _eligible_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    curation_statuses: set[str],
    categories: set[str],
    difficulties: set[str],
    ambiguities: set[str],
    require_exact_labels: bool,
    output_schema_version: str,
    output_curation_status: str,
    output_label_source: str,
) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for row in rows:
        source_status = str(row.get("curation_status") or "")
        category = str(row.get("category") or "")
        difficulty = _derive_difficulty(row)
        ambiguity = _derive_ambiguity(row)
        if curation_statuses and source_status not in curation_statuses:
            continue
        if categories and category not in categories:
            continue
        if difficulties and difficulty not in difficulties:
            continue
        if ambiguities and ambiguity not in ambiguities:
            continue
        if require_exact_labels and not _has_exact_labels(row):
            continue
        normalized = _normalize_row(
            row,
            output_schema_version=output_schema_version,
            output_curation_status=output_curation_status,
            output_label_source=output_label_source,
        )
        eligible.append(normalized)
    return eligible


def _selection_key(row: Mapping[str, Any]) -> tuple[int, int, int, str]:
    ambiguity = str(row.get("ambiguity") or "")
    difficulty = str(row.get("difficulty") or "")
    return (
        AMBIGUITY_RANK.get(ambiguity, 99),
        DIFFICULTY_RANK.get(difficulty, 99),
        _label_complexity(row),
        str(row.get("task_id") or ""),
    )


def _sample_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    per_category: int | None,
    max_tasks: int | None,
    seed: int,
) -> list[dict[str, Any]]:
    if max_tasks == 0:
        return []

    rng = random.Random(seed)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("category") or "")].append(dict(row))

    sampled_by_category: dict[str, list[dict[str, Any]]] = {}
    for category in sorted(grouped):
        category_rows = sorted(grouped[category], key=_selection_key)
        if per_category is not None and per_category >= 0:
            take = min(per_category, len(category_rows))
            ranked_candidates: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
            for row in category_rows:
                rank = _selection_key(row)[:3]
                ranked_candidates[rank].append(row)
            selected: list[dict[str, Any]] = []
            for rank in sorted(ranked_candidates):
                candidates = ranked_candidates[rank][:]
                rng.shuffle(candidates)
                for row in candidates:
                    selected.append(row)
                    if len(selected) == take:
                        break
                if len(selected) == take:
                    break
            sampled_by_category[category] = selected
        else:
            sampled_by_category[category] = category_rows

    selected = [row for category in sorted(sampled_by_category) for row in sampled_by_category[category]]
    if max_tasks is not None and max_tasks >= 0 and len(selected) > max_tasks:
        balanced: list[dict[str, Any]] = []
        categories = sorted(sampled_by_category)
        max_depth = max(len(category_rows) for category_rows in sampled_by_category.values())
        for depth in range(max_depth):
            depth_categories = categories[:]
            rng.shuffle(depth_categories)
            for category in depth_categories:
                category_rows = sampled_by_category[category]
                if depth >= len(category_rows):
                    continue
                balanced.append(category_rows[depth])
                if len(balanced) == max_tasks:
                    selected = balanced
                    break
            if len(balanced) == max_tasks:
                break

    return sorted(
        selected,
        key=lambda item: (str(item.get("category") or ""), str(item.get("task_id") or "")),
    )


def _summary(
    *,
    source_jsonl: Path,
    input_rows: int,
    eligible_rows: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
    curation_statuses: Sequence[str],
    categories: Sequence[str],
    difficulties: Sequence[str],
    ambiguities: Sequence[str],
    per_category: int | None,
    max_tasks: int | None,
    seed: int,
    output_schema_version: str,
    output_curation_status: str,
    output_label_source: str,
) -> dict[str, Any]:
    label_counts = [_label_complexity(row) for row in selected_rows]
    return {
        "schema_version": "br.microtooling_exact_benchmark.summary.v1",
        "source_jsonl": str(source_jsonl),
        "input_rows": input_rows,
        "eligible_rows": len(eligible_rows),
        "selected_rows": len(selected_rows),
        "selection": {
            "curation_statuses": list(curation_statuses),
            "categories": list(categories),
            "difficulties": list(difficulties),
            "ambiguities": list(ambiguities),
            "per_category": per_category,
            "max_tasks": max_tasks,
            "seed": seed,
        },
        "output": {
            "schema_version": output_schema_version,
            "curation_status": output_curation_status,
            "label_source": output_label_source,
        },
        "category_counts": dict(
            sorted(Counter(str(row.get("category") or "") for row in selected_rows).items())
        ),
        "curation_status_counts": dict(
            sorted(Counter(str(row.get("curation_status") or "") for row in selected_rows).items())
        ),
        "difficulty_counts": dict(
            sorted(Counter(str(row.get("difficulty") or "") for row in selected_rows).items())
        ),
        "ambiguity_counts": dict(
            sorted(Counter(str(row.get("ambiguity") or "") for row in selected_rows).items())
        ),
        "exact_label_counts": {
            "min": min(label_counts) if label_counts else None,
            "max": max(label_counts) if label_counts else None,
            "mean": sum(label_counts) / float(len(label_counts)) if label_counts else None,
        },
    }


def generate_benchmark(
    *,
    source_jsonl: Path,
    curation_statuses: Sequence[str],
    categories: Sequence[str],
    difficulties: Sequence[str],
    ambiguities: Sequence[str],
    per_category: int | None,
    max_tasks: int | None,
    seed: int,
    require_exact_labels: bool = True,
    output_schema_version: str = DEFAULT_OUTPUT_SCHEMA_VERSION,
    output_curation_status: str = DEFAULT_OUTPUT_CURATION_STATUS,
    output_label_source: str = DEFAULT_OUTPUT_LABEL_SOURCE,
) -> dict[str, Any]:
    rows = _load_jsonl(source_jsonl)
    eligible = _eligible_rows(
        rows,
        curation_statuses=set(curation_statuses),
        categories=set(categories),
        difficulties=set(difficulties),
        ambiguities=set(ambiguities),
        require_exact_labels=require_exact_labels,
        output_schema_version=output_schema_version,
        output_curation_status=output_curation_status,
        output_label_source=output_label_source,
    )
    selected = _sample_rows(
        eligible,
        per_category=per_category,
        max_tasks=max_tasks,
        seed=seed,
    )
    return {
        "rows": selected,
        "summary": _summary(
            source_jsonl=source_jsonl,
            input_rows=len(rows),
            eligible_rows=eligible,
            selected_rows=selected,
            curation_statuses=curation_statuses,
            categories=categories,
            difficulties=difficulties,
            ambiguities=ambiguities,
            per_category=per_category,
            max_tasks=max_tasks,
            seed=seed,
            output_schema_version=output_schema_version,
            output_curation_status=output_curation_status,
            output_label_source=output_label_source,
        ),
    }


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_labels.autocurated.v1.labels.jsonl",
    )
    parser.add_argument("--out-jsonl", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, default=None)
    parser.add_argument("--curation-status", action="append", default=None)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--difficulty", action="append", default=[])
    parser.add_argument("--ambiguity", action="append", default=[])
    parser.add_argument("--per-category", type=int, default=DEFAULT_PER_CATEGORY)
    parser.add_argument("--max-tasks", type=int, default=DEFAULT_MAX_TASKS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-schema-version", default=DEFAULT_OUTPUT_SCHEMA_VERSION)
    parser.add_argument("--output-curation-status", default=DEFAULT_OUTPUT_CURATION_STATUS)
    parser.add_argument("--output-label-source", default=DEFAULT_OUTPUT_LABEL_SOURCE)
    parser.add_argument(
        "--allow-missing-exact-labels",
        action="store_true",
        help="Include rows without any exact tool, family, or sequence labels.",
    )
    args = parser.parse_args()

    payload = generate_benchmark(
        source_jsonl=args.source_jsonl,
        curation_statuses=args.curation_status or ["auto_curated"],
        categories=args.category,
        difficulties=args.difficulty,
        ambiguities=args.ambiguity,
        per_category=args.per_category,
        max_tasks=args.max_tasks,
        seed=args.seed,
        require_exact_labels=not args.allow_missing_exact_labels,
        output_schema_version=args.output_schema_version,
        output_curation_status=args.output_curation_status,
        output_label_source=args.output_label_source,
    )
    _write_jsonl(args.out_jsonl, payload["rows"])
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(
            json.dumps(payload["summary"], indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
