"""Tests for family-card tool_search A/B harness."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "tool_search_family_routing_ab.py"
SPEC = importlib.util.spec_from_file_location(
    "tool_search_family_routing_ab", SCRIPT_PATH
)
assert SPEC is not None
assert SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _patch_exact_eval_catalog(monkeypatch: Any) -> None:
    catalog = {
        "tool.cards": SimpleNamespace(),
        "tool.legacy": SimpleNamespace(),
        "tool.other": SimpleNamespace(),
    }
    monkeypatch.setattr(
        harness.exact_eval,
        "get_capability_index",
        lambda: SimpleNamespace(by_id=catalog),
    )
    monkeypatch.setattr(harness.exact_eval, "load_tool_families", lambda: {})


def _fake_tool_search(query: str, *, limit: int, exposed_only: bool) -> dict[str, Any]:
    del limit, exposed_only
    mode = os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE")
    if query == "legacy wins":
        top = "tool.legacy" if mode == "legacy" else "tool.cards"
    elif query == "cards wins":
        top = "tool.legacy" if mode == "legacy" else "tool.cards"
    else:
        top = "tool.other"
    return {"tools": [{"name": top}], "total_matches": 1}


def test_tool_search_mode_restores_environment(monkeypatch: Any) -> None:
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "outer")
    monkeypatch.delenv("BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE", raising=False)

    with harness._tool_search_mode("cards"):
        assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "cards"
        assert os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] == "cards"

    assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "outer"
    assert "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE" not in os.environ


def test_family_routing_ab_writes_mode_comparison(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _patch_exact_eval_catalog(monkeypatch)
    monkeypatch.setattr(harness, "_run_tool_search", _fake_tool_search)
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "outer")
    monkeypatch.setenv("BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE", "outer")

    labels = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "T-legacy",
                "query": "legacy wins",
                "exact_labels": {"expected_tool_ids": ["tool.legacy"]},
            },
            {
                "task_id": "T-cards",
                "query": "cards wins",
                "exact_labels": {"expected_tool_ids": ["tool.cards"]},
            },
        ],
    )

    payload = harness.run_ab(
        labels_jsonl=labels,
        output_dir=tmp_path / "run",
        limit=5,
        exposed_only=True,
        max_tasks=2,
        k_values=[1],
    )

    assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "outer"
    assert os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] == "outer"
    assert payload["summary"]["legacy"]["evaluated_tasks"] == 2
    assert payload["summary"]["cards"]["evaluated_tasks"] == 2
    assert payload["summary"]["legacy"]["skipped_missing_predictions"] == 0
    assert payload["summary"]["cards"]["skipped_missing_predictions"] == 0
    assert payload["summary"]["legacy"]["tool_recall_at_1"] == 0.5
    assert payload["summary"]["cards"]["tool_recall_at_1"] == 0.5
    assert payload["summary"]["top1_delta_count"] == 2
    assert (tmp_path / "run" / "labels.evaluated.jsonl").exists()

    predictions = json.loads((tmp_path / "run" / "predictions.json").read_text())
    assert {row["mode"] for row in predictions} == {"legacy", "cards"}
    assert {row["task_id"] for row in predictions} == {"T-legacy", "T-cards"}

    deltas = [
        json.loads(line)
        for line in (tmp_path / "run" / "top1_deltas.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert {row["delta"] for row in deltas} == {"cards_gain", "cards_regression"}
    report = (tmp_path / "run" / "report.md").read_text(encoding="utf-8")
    assert "Family-Card Tool Search A/B" in report
    assert "Default runtime mode is unchanged" in report
