"""Regression tests for bounded MicroTooling exact benchmark generation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "generate_microtooling_exact_benchmark.py"
SPEC = importlib.util.spec_from_file_location("generate_microtooling_exact_benchmark", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_generate_filters_curated_exact_rows_and_derives_metadata(tmp_path: Path) -> None:
    source = tmp_path / "labels.jsonl"
    _write_jsonl(
        source,
        [
            {
                "schema_version": "br.tool_routing_exact_labels.v1",
                "task_id": "A-001",
                "category": "Alpha",
                "query": "Run a single exact tool",
                "weak_expected_capabilities": "alpha_tool",
                "curation_status": "auto_curated",
                "exact_labels": {"expected_tool_ids": ["tool.a"]},
                "label_source": "unit",
            },
            {
                "task_id": "A-002",
                "category": "Alpha",
                "query": "Run several acceptable tools",
                "curation_status": "auto_curated",
                "exact_labels": {
                    "expected_tool_ids": ["tool.b", "tool.c"],
                    "acceptable_tool_ids": ["tool.d", "tool.e", "tool.f", "tool.g", "tool.h", "tool.i"],
                },
            },
            {
                "task_id": "B-001",
                "category": "Beta",
                "query": "Use a family",
                "curation_status": "auto_curated",
                "difficulty": "reviewer_hard",
                "ambiguity": "reviewer_low",
                "exact_labels": {"expected_family_ids": ["fam.beta"]},
            },
            {
                "task_id": "B-002",
                "category": "Beta",
                "query": "Missing exact labels",
                "curation_status": "auto_curated",
                "exact_labels": {},
            },
            {
                "task_id": "C-001",
                "category": "Gamma",
                "query": "Needs review",
                "curation_status": "needs_manual_review",
                "exact_labels": {"expected_tool_ids": ["tool.z"]},
            },
        ],
    )

    payload = generator.generate_benchmark(
        source_jsonl=source,
        curation_statuses=["auto_curated"],
        categories=[],
        difficulties=[],
        ambiguities=[],
        per_category=1,
        max_tasks=10,
        seed=7,
    )

    rows = payload["rows"]
    assert len(rows) == 2
    assert {row["category"] for row in rows} == {"Alpha", "Beta"}
    assert all(row["schema_version"] == "br.tool_routing_exact_labels.curated.v1" for row in rows)
    assert all(row["curation_status"] == "curated_candidate" for row in rows)
    assert all(row["source_curation_status"] == "auto_curated" for row in rows)
    assert all(
        row["label_source"] == "deterministic_curated_subset_from_autocurated_seed.v1"
        for row in rows
    )
    assert all(row["exact_labels"] for row in rows)

    by_task = {row["task_id"]: row for row in rows}
    assert by_task["B-001"]["difficulty"] == "reviewer_hard"
    assert by_task["B-001"]["ambiguity"] == "reviewer_low"
    assert payload["summary"]["input_rows"] == 5
    assert payload["summary"]["eligible_rows"] == 3
    assert payload["summary"]["selected_rows"] == 2
    assert payload["summary"]["category_counts"] == {"Alpha": 1, "Beta": 1}
    assert payload["summary"]["output"]["curation_status"] == "curated_candidate"


def test_generate_respects_difficulty_filter_and_global_bound(tmp_path: Path) -> None:
    source = tmp_path / "labels.jsonl"
    _write_jsonl(
        source,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "curation_status": "auto_curated",
                "exact_labels": {"expected_tool_ids": ["tool.a"]},
            },
            {
                "task_id": "A-002",
                "category": "Alpha",
                "curation_status": "auto_curated",
                "exact_labels": {"expected_tool_ids": ["tool.b", "tool.c"]},
            },
            {
                "task_id": "B-001",
                "category": "Beta",
                "curation_status": "auto_curated",
                "exact_labels": {"expected_tool_ids": ["tool.d"], "expected_sequence_tool_ids": ["tool.e"]},
            },
        ],
    )

    first = generator.generate_benchmark(
        source_jsonl=source,
        curation_statuses=["auto_curated"],
        categories=[],
        difficulties=["medium", "hard"],
        ambiguities=[],
        per_category=None,
        max_tasks=1,
        seed=3,
    )
    second = generator.generate_benchmark(
        source_jsonl=source,
        curation_statuses=["auto_curated"],
        categories=[],
        difficulties=["medium", "hard"],
        ambiguities=[],
        per_category=None,
        max_tasks=1,
        seed=3,
    )

    assert first["rows"] == second["rows"]
    assert first["summary"]["eligible_rows"] == 2
    assert first["summary"]["selected_rows"] == 1
    assert first["rows"][0]["difficulty"] in {"medium", "hard"}


def test_generate_defaults_to_264_row_balanced_candidate_subset() -> None:
    assert generator.DEFAULT_PER_CATEGORY == 12
    assert generator.DEFAULT_MAX_TASKS == 264
    assert generator.DEFAULT_OUTPUT_CURATION_STATUS == "curated_candidate"


def test_generate_allows_zero_task_diagnostic_subset(tmp_path: Path) -> None:
    source = tmp_path / "labels.jsonl"
    _write_jsonl(
        source,
        [
            {
                "task_id": "A-001",
                "category": "Alpha",
                "curation_status": "auto_curated",
                "exact_labels": {"expected_tool_ids": ["tool.a"]},
            }
        ],
    )

    payload = generator.generate_benchmark(
        source_jsonl=source,
        curation_statuses=["auto_curated"],
        categories=[],
        difficulties=[],
        ambiguities=[],
        per_category=None,
        max_tasks=0,
        seed=3,
    )

    assert payload["rows"] == []
    assert payload["summary"]["eligible_rows"] == 1
    assert payload["summary"]["selected_rows"] == 0
