"""Regression tests for exact-label tool-routing evaluation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "evaluate_exact_tool_routing.py"
SPEC = importlib.util.spec_from_file_location("evaluate_exact_tool_routing", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
exact_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exact_eval)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _patch_catalog(monkeypatch: Any) -> None:
    catalog = {
        "tool.a": SimpleNamespace(),
        "tool.b": SimpleNamespace(),
        "tool.c": SimpleNamespace(),
        "tool.x": SimpleNamespace(),
    }
    families = {
        "fam.preproc": SimpleNamespace(
            id="fam.preproc",
            ops={"a": "tool.a", "b": "tool.b"},
        ),
        "fam.other": SimpleNamespace(id="fam.other", ops={"c": "tool.c"}),
    }
    monkeypatch.setattr(
        exact_eval,
        "get_capability_index",
        lambda: SimpleNamespace(by_id=catalog),
    )
    monkeypatch.setattr(exact_eval, "load_tool_families", lambda: families)


def test_uncurated_labels_are_skipped(tmp_path: Path, monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)
    labels = tmp_path / "labels.jsonl"
    predictions = tmp_path / "predictions.json"
    _write_jsonl(
        labels,
        [
            {"task_id": "T1", "exact_labels": {}},
            {"task_id": "T2", "exact_labels": {"expected_tool_ids": []}},
        ],
    )
    predictions.write_text(
        json.dumps([{"task_id": "T1", "top_tool_ids": ["tool.a"]}]),
        encoding="utf-8",
    )

    payload = exact_eval.evaluate(
        labels_jsonl=labels,
        predictions_json=predictions,
        mode=None,
        k_values=[1, 3],
    )

    assert payload["summary"]["evaluated_tasks"] == 0
    assert payload["summary"]["skipped_missing_exact_labels"] == 2
    assert payload["summary"]["tool_recall_at_1"] is None
    assert payload["summary"]["wrong_tool_top1_rate"] is None


def test_curated_catalog_labels_are_scored(tmp_path: Path, monkeypatch: Any) -> None:
    _patch_catalog(monkeypatch)
    labels = tmp_path / "labels.jsonl"
    predictions = tmp_path / "predictions.json"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "T1",
                "category": "preproc",
                "exact_labels": {
                    "expected_tool_ids": ["tool.a"],
                    "expected_family_ids": ["fam.preproc"],
                    "expected_sequence_tool_ids": ["tool.a", "tool.b"],
                },
            },
            {
                "task_id": "T2",
                "category": "stats",
                "exact_labels": {"expected_tool_ids": ["tool.x"]},
            },
        ],
    )
    predictions.write_text(
        json.dumps(
            [
                {"task_id": "T1", "top_tool_ids": ["tool.a", "tool.b", "tool.c"]},
                {"task_id": "T2", "top_tool_ids": ["tool.c"], "latency_ms": 20.0},
            ]
        ),
        encoding="utf-8",
    )

    payload = exact_eval.evaluate(
        labels_jsonl=labels,
        predictions_json=predictions,
        mode=None,
        k_values=[1, 3],
    )

    summary = payload["summary"]
    assert summary["evaluated_tasks"] == 2
    assert summary["invalid_label_count"] == 0
    assert summary["tool_recall_at_1"] == 0.5
    assert summary["tool_recall_at_3"] == 0.5
    assert summary["family_recall_at_1"] == 1.0
    assert summary["sequence_recall_at_1"] == 0.0
    assert summary["sequence_recall_at_3"] == 1.0
    assert summary["wrong_tool_top1_rate"] == 0.5
    assert summary["latency_count"] == 1
    assert summary["latency_mean_ms"] == 20.0
    assert summary["latency_median_ms"] == 20.0
    assert summary["latency_p95_ms"] == 20.0
