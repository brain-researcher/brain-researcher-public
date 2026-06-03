"""Regression tests for MicroTooling exact-label autocuration."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from brain_researcher.services.agent.planner.catalog_loader import get_capability_index
from brain_researcher.services.agent.tool_router import load_tool_families

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "curate_microtooling_exact_labels.py"
SPEC = importlib.util.spec_from_file_location("curate_microtooling_exact_labels", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
curator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = curator
SPEC.loader.exec_module(curator)

MANUAL_CURATED_V2 = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "microtooling_exact_labels.manual_curated.v2.labels.jsonl"
)
MANUAL_CURATED_V2_SUMMARY = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "microtooling_exact_labels.manual_curated.v2.summary.json"
)
PASS3_AUDIT = (
    ROOT
    / "benchmarks"
    / "tool_routing_validation"
    / "manual_audit"
    / "microtooling_manual_audit_pass3_completion.v2.jsonl"
)


def _patch_catalog(monkeypatch: Any) -> None:
    catalog = {
        "clean_confounds": SimpleNamespace(name="Clean Confounds", capabilities=["preprocessing"], intents=[]),
        "consult_knowledge_graph": SimpleNamespace(name="Consult Knowledge Graph", capabilities=["br_kg"], intents=[]),
        "find_related_concepts": SimpleNamespace(name="Find Related Concepts", capabilities=["br_kg"], intents=[]),
        "graph_theory": SimpleNamespace(name="Graph Theory", capabilities=["graph_theory"], intents=[]),
        "group_ica": SimpleNamespace(name="Group ICA", capabilities=["ica"], intents=[]),
        "multiple_comparison_correction": SimpleNamespace(
            name="Multiple Comparison Correction",
            capabilities=["preprocessing"],
            intents=[],
        ),
        "br_kg.search_nodes": SimpleNamespace(name="Search Nodes", capabilities=["search"], intents=[]),
        "br_kg_find_related_concepts": SimpleNamespace(name="Related Concepts", capabilities=["br_kg"], intents=[]),
        "br_kg_graph_query": SimpleNamespace(name="BRKG Graph Query", capabilities=["br_kg"], intents=[]),
        "nilearn_ica": SimpleNamespace(name="Nilearn ICA", capabilities=["ica"], intents=[]),
        "nilearn_preprocessing_tool": SimpleNamespace(
            name="Nilearn Preprocessing",
            capabilities=["preprocessing"],
            intents=[],
        ),
        "query_bids_layout": SimpleNamespace(name="Query BIDS Layout", capabilities=["bids_query"], intents=[]),
        "validate_bids_structure": SimpleNamespace(name="Validate BIDS", capabilities=["bids"], intents=[]),
    }
    monkeypatch.setattr(
        curator,
        "get_capability_index",
        lambda: SimpleNamespace(by_id=catalog),
    )
    monkeypatch.setattr(curator, "load_tool_families", lambda: {})


def test_knowledge_graph_label_prefers_kg_tools(monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)

    rows, summary = curator.curate_rows(
        [
            {
                "task_id": "KG-001",
                "category": "Knowledge Graph",
                "query": "Build brain region knowledge graph from an atlas",
                "context": "",
                "weak_expected_capabilities": ["knowledge_graph_tool"],
            }
        ]
    )

    labels = rows[0]["exact_labels"]
    assert summary["rows_without_expected_tool_ids"] == 0
    assert labels["expected_tool_ids"] == [
        "br_kg_graph_query",
        "find_related_concepts",
    ]
    assert "graph_theory" in labels["acceptable_tool_ids"]


def test_generic_preprocessing_capability_is_not_exact_promoted(monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)

    rows, _ = curator.curate_rows(
        [
            {
                "task_id": "PREP-003",
                "category": "Preprocessing",
                "query": "Apply slice timing correction",
                "context": "",
                "weak_expected_capabilities": ["preprocessing"],
            }
        ]
    )

    labels = rows[0]["exact_labels"]
    assert labels["expected_tool_ids"] == ["nilearn_preprocessing_tool"]
    assert "multiple_comparison_correction" not in labels["expected_tool_ids"]


def test_task_text_rule_handles_tedana_specialized_task(monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)

    rows, _ = curator.curate_rows(
        [
            {
                "task_id": "SPEC-001",
                "category": "Specialized Processing",
                "query": "Apply TEDANA multi-echo denoising",
                "context": "separate BOLD from non-BOLD signals",
                "weak_expected_capabilities": ["specialized_processing_tool"],
            }
        ]
    )

    labels = rows[0]["exact_labels"]
    assert labels["expected_tool_ids"] == [
        "group_ica",
        "nilearn_preprocessing_tool",
    ]
    assert "nilearn_ica" in labels["acceptable_tool_ids"]


def test_load_seed_rows_falls_back_to_microtooling_json(tmp_path: Path) -> None:
    source = tmp_path / "microtooling.json"
    source.write_text(
        """
        [
          {
            "task_id": "DATA-001",
            "task_category": "Data Management",
            "user_prompt": "Fetch and validate BIDS structure",
            "context_block": "Check BIDS filenames",
            "expected_capability_list": ["bids_tools"]
          }
        ]
        """,
        encoding="utf-8",
    )

    rows = curator._load_seed_rows(tmp_path / "missing.jsonl", source)

    assert rows == [
        {
            "schema_version": "br.tool_routing_exact_label_seed.v1",
            "task_id": "DATA-001",
            "category": "Data Management",
            "query": "Fetch and validate BIDS structure",
            "context": "Check BIDS filenames",
            "weak_expected_capabilities": ["bids_tools"],
            "exact_labels": {
                "expected_tool_ids": [],
                "acceptable_tool_ids": [],
                "expected_family_ids": [],
                "expected_sequence_tool_ids": [],
            },
        }
    ]


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_manual_curated_v2_completes_all_microtooling_rows() -> None:
    rows = _jsonl_rows(MANUAL_CURATED_V2)
    summary = json.loads(MANUAL_CURATED_V2_SUMMARY.read_text(encoding="utf-8"))
    pass3_rows = _jsonl_rows(PASS3_AUDIT)

    assert len(rows) == 440
    assert len({row["task_id"] for row in rows}) == 440
    assert len(pass3_rows) == 192
    assert summary["accepted_rows"] == 440
    assert summary["existing_manual_rows"] == 248
    assert summary["completed_rows"] == 192
    assert summary["invalid_label_count"] == 0
    assert not summary["source_jsonl"].startswith("/")
    assert not summary["existing_manual_jsonl"].startswith("/")
    assert all(not path.startswith("/") for path in summary["audit_jsonls"])
    assert summary["category_balance"] == {
        "category_count": 22,
        "max": 20,
        "min": 20,
    }
    category_counts = Counter(row["category"] for row in rows)
    assert len(category_counts) == 22
    assert set(category_counts.values()) == {20}

    assert {row["curation_status"] for row in rows} == {"manual_curated"}
    assert all(row.get("manual_audit") for row in rows)
    assert all(row.get("difficulty") in {"easy", "medium", "hard"} for row in rows)
    assert all(row.get("ambiguity") in {"low", "medium", "high"} for row in rows)
    assert all((row.get("exact_labels") or {}).get("expected_tool_ids") for row in rows)


def test_manual_curated_v2_labels_are_catalog_backed() -> None:
    rows = _jsonl_rows(MANUAL_CURATED_V2)
    catalog_tool_ids = set(get_capability_index().by_id)
    family_ids = set(load_tool_families())
    invalid: list[tuple[str, str, str]] = []

    for row in rows:
        labels = row.get("exact_labels") or {}
        for field in ("expected_tool_ids", "acceptable_tool_ids", "expected_sequence_tool_ids"):
            for tool_id in labels.get(field) or []:
                if tool_id not in catalog_tool_ids:
                    invalid.append((row["task_id"], field, tool_id))
        for family_id in labels.get("expected_family_ids") or []:
            if family_id not in family_ids:
                invalid.append((row["task_id"], "expected_family_ids", family_id))

    assert invalid == []


def test_manual_curated_v2_has_manuscript_grade_sequence_band() -> None:
    rows = _jsonl_rows(MANUAL_CURATED_V2)
    sequence_rows = [
        row
        for row in rows
        if (row.get("exact_labels") or {}).get("expected_sequence_tool_ids")
    ]

    assert 50 <= len(sequence_rows) <= 80
    assert any(row["task_id"] == "DATA-001" for row in sequence_rows)
    assert any(row["task_id"] == "WORK-001" for row in sequence_rows)
