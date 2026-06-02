#!/usr/bin/env python3
"""Build a curation draft for exact MicroTooling router labels.

The existing MicroTooling benchmark uses weak capability labels such as
``ants_tool`` or ``data_management_tool``. This script preserves those labels as
provenance, but does not treat them as exact tool truth. It emits JSONL/CSV rows
that a reviewer can fill with catalog-backed ``expected_tool_ids`` and
``expected_family_ids``.
"""

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


def _load_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_codex_rows(path: Path | None) -> dict[str, dict[str, list[str]]]:
    data = _load_json(path)
    by_task: dict[str, dict[str, list[str]]] = {}
    if not isinstance(data, list):
        return by_task
    for row in data:
        if not isinstance(row, Mapping):
            continue
        task_id = str(row.get("task_id") or "").strip()
        mode = str(row.get("mode") or "").strip()
        if not task_id or not mode:
            continue
        tools = _as_list(row.get("predicted_top5_valid") or row.get("top_tool_ids"))
        by_task.setdefault(task_id, {})[mode] = tools[:5]
    return by_task


def _load_planner_rows(path: Path | None) -> dict[str, list[str]]:
    data = _load_json(path)
    if not isinstance(data, Mapping):
        return {}
    rows = (
        ((data.get("tracks") or {}).get("tools") or {}).get("results")
        or (data.get("baseline") or {}).get("results")
        or []
    )
    out: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        task_id = str(row.get("task_id") or "").strip()
        if task_id:
            out[task_id] = _as_list(row.get("top_tool_ids"))[:5]
    return out


def _tool_to_family_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for family in load_tool_families().values():
        for tool_id in family.ops.values():
            if tool_id and tool_id not in out:
                out[str(tool_id)] = family.id
    return out


def _candidate_record(
    tool_id: str,
    *,
    sources: Sequence[str],
    catalog: Mapping[str, Any],
    tool_to_family: Mapping[str, str],
) -> dict[str, Any]:
    tool = catalog.get(tool_id)
    return {
        "tool_id": tool_id,
        "exists_in_catalog": tool is not None,
        "family_id": tool_to_family.get(tool_id),
        "sources": list(sources),
        "catalog_capabilities": list(getattr(tool, "capabilities", []) or [])
        if tool is not None
        else [],
        "catalog_intents": list(getattr(tool, "intents", []) or [])
        if tool is not None
        else [],
        "description": (getattr(tool, "description", None) or "") if tool is not None else "",
    }


def _candidate_pool(
    source_lists: Mapping[str, Sequence[str]],
    *,
    catalog: Mapping[str, Any],
    tool_to_family: Mapping[str, str],
) -> list[dict[str, Any]]:
    sources_by_tool: dict[str, list[str]] = {}
    tool_order: list[str] = []
    for source, tool_ids in source_lists.items():
        for tool_id in tool_ids:
            if not tool_id:
                continue
            normalized_tool_id = str(tool_id)
            if normalized_tool_id not in sources_by_tool:
                tool_order.append(normalized_tool_id)
            sources_by_tool.setdefault(normalized_tool_id, []).append(source)
    return [
        _candidate_record(
            tool_id,
            sources=sources_by_tool[tool_id],
            catalog=catalog,
            tool_to_family=tool_to_family,
        )
        for tool_id in tool_order
    ]


def _label_overlap(
    weak_labels: Sequence[str],
    *,
    catalog: Mapping[str, Any],
) -> dict[str, list[str]]:
    weak_set = {str(label).strip() for label in weak_labels if str(label).strip()}
    catalog_capabilities: set[str] = set()
    catalog_intents: set[str] = set()
    for tool in catalog.values():
        catalog_capabilities.update(str(x) for x in (getattr(tool, "capabilities", []) or []))
        catalog_intents.update(str(x) for x in (getattr(tool, "intents", []) or []))
    return {
        "exact_tool_ids": sorted(weak_set.intersection(catalog.keys())),
        "exact_catalog_capabilities": sorted(weak_set.intersection(catalog_capabilities)),
        "exact_catalog_intents": sorted(weak_set.intersection(catalog_intents)),
    }


def build_rows(
    *,
    microtooling_json: Path,
    planner_results_json: Path | None,
    codex_rows_json: Path | None,
) -> list[dict[str, Any]]:
    tasks = json.loads(microtooling_json.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError(f"{microtooling_json} must be a JSON list")

    index = get_capability_index()
    catalog = index.by_id
    tool_to_family = _tool_to_family_map()
    planner_by_task = _load_planner_rows(planner_results_json)
    codex_by_task = _load_codex_rows(codex_rows_json)

    rows: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        task_id = str(task.get("task_id") or "").strip()
        query = str(task.get("user_prompt") or task.get("query") or "").strip()
        if not task_id or not query:
            continue
        weak_labels = _as_list(
            task.get("expected_capability_list") or task.get("expected_capability")
        )
        source_lists: dict[str, Sequence[str]] = {}
        if task_id in planner_by_task:
            source_lists["br_unified_planner_top5"] = planner_by_task[task_id]
        for mode, tool_ids in sorted(codex_by_task.get(task_id, {}).items()):
            source_lists[f"{mode}_top5"] = tool_ids

        rows.append(
            {
                "schema_version": "br.tool_routing_exact_label_draft.v1",
                "task_id": task_id,
                "category": task.get("task_category") or task.get("category"),
                "query": query,
                "context": task.get("context_block") or task.get("context"),
                "weak_expected_capabilities": weak_labels,
                "weak_label_catalog_overlap": _label_overlap(weak_labels, catalog=catalog),
                "candidate_sources": source_lists,
                "candidate_pool": _candidate_pool(
                    source_lists,
                    catalog=catalog,
                    tool_to_family=tool_to_family,
                ),
                "exact_labels": {
                    "expected_tool_ids": [],
                    "acceptable_tool_ids": [],
                    "expected_family_ids": [],
                    "expected_sequence_tool_ids": [],
                },
                "curation_status": "needs_manual_review",
                "label_source": "manual_required",
            }
        )
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "task_id",
        "category",
        "query",
        "weak_expected_capabilities",
        "candidate_tool_ids",
        "candidate_family_ids",
        "expected_tool_ids",
        "acceptable_tool_ids",
        "expected_family_ids",
        "expected_sequence_tool_ids",
        "curation_status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            pool = list(row.get("candidate_pool") or [])
            candidate_tool_ids = [item.get("tool_id") for item in pool if item.get("tool_id")]
            candidate_family_ids = sorted(
                {item.get("family_id") for item in pool if item.get("family_id")}
            )
            labels = row.get("exact_labels") or {}
            writer.writerow(
                {
                    "task_id": row.get("task_id"),
                    "category": row.get("category"),
                    "query": row.get("query"),
                    "weak_expected_capabilities": "; ".join(
                        row.get("weak_expected_capabilities") or []
                    ),
                    "candidate_tool_ids": "; ".join(candidate_tool_ids),
                    "candidate_family_ids": "; ".join(candidate_family_ids),
                    "expected_tool_ids": "; ".join(labels.get("expected_tool_ids") or []),
                    "acceptable_tool_ids": "; ".join(
                        labels.get("acceptable_tool_ids") or []
                    ),
                    "expected_family_ids": "; ".join(
                        labels.get("expected_family_ids") or []
                    ),
                    "expected_sequence_tool_ids": "; ".join(
                        labels.get("expected_sequence_tool_ids") or []
                    ),
                    "curation_status": row.get("curation_status"),
                }
            )


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--microtooling-json",
        type=Path,
        default=root / "docs" / "BrainRearcherBenchmark_MicroTooling.json",
    )
    parser.add_argument(
        "--planner-results-json",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_440_semantic_20260503.json",
    )
    parser.add_argument(
        "--codex-rows-json",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "codex_microtooling_pilot_20260503"
        / "codex_br_pilot_rows.json",
    )
    parser.add_argument(
        "--out-jsonl",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_label_draft.v1.jsonl",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=root
        / "benchmarks"
        / "tool_routing_validation"
        / "microtooling_exact_label_draft.v1.csv",
    )
    args = parser.parse_args()

    rows = build_rows(
        microtooling_json=args.microtooling_json,
        planner_results_json=args.planner_results_json,
        codex_rows_json=args.codex_rows_json,
    )
    _write_jsonl(args.out_jsonl, rows)
    _write_csv(args.out_csv, rows)
    print(
        json.dumps(
            {
                "tasks": len(rows),
                "out_jsonl": str(args.out_jsonl),
                "out_csv": str(args.out_csv),
                "curation_status": "needs_manual_review",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
