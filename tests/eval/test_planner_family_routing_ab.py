"""Tests for the planner KG-fallback family-routing A/B harness."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "planner_family_routing_ab.py"
SPEC = importlib.util.spec_from_file_location("planner_family_routing_ab", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


class _Match:
    def __init__(self, tool_id: str, score: float) -> None:
        self.id = tool_id
        self.score = score


class _FakeRetriever:
    calls: list[dict[str, Any]] = []
    closes = 0

    def __init__(self) -> None:
        self.mode = os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE")

    def select_families_by_query(
        self, query: str, llm: Any = None, max_families: int = 3
    ) -> list[str]:
        _FakeRetriever.calls.append(
            {
                "method": "select",
                "mode": self.mode,
                "query": query,
                "llm": llm,
                "max_families": max_families,
            }
        )
        if query == "No family query" and self.mode == "cards":
            return []
        return [f"{self.mode}.family"]

    def retrieve_tools(
        self,
        query: str,
        family_ids: list[str] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[_Match]:
        _FakeRetriever.calls.append(
            {
                "method": "retrieve",
                "mode": self.mode,
                "query": query,
                "family_ids": family_ids,
                "top_k": top_k,
                "filters": filters,
            }
        )
        if self.mode == "legacy":
            return [_Match("fmri_tool", 0.9), _Match("empty_modality_tool", 0.5)]
        return [_Match("meg_tool", 0.95)]

    def close(self) -> None:
        _FakeRetriever.closes += 1


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _fake_factory() -> _FakeRetriever:
    return _FakeRetriever()


def test_family_routing_mode_restores_environment(monkeypatch: Any) -> None:
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "outer")

    with harness._family_routing_mode("cards"):
        assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "cards"

    assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "outer"


def test_planner_family_ab_reports_proxy_counts_and_modality_diffs(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _FakeRetriever.calls = []
    _FakeRetriever.closes = 0
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "outer")

    labels = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "MEG-001",
                "query": "Estimate MEG connectivity",
            },
            {
                "task_id": "NONE-001",
                "query": "No family query",
            },
        ],
    )

    payload = harness.run_ab(
        labels_jsonl=labels,
        output_dir=tmp_path / "out",
        max_tasks=None,
        max_families=2,
        top_k=2,
        retriever_factory=_fake_factory,
        tool_modalities={
            "fmri_tool": ["fmri"],
            "meg_tool": ["meg"],
            "empty_modality_tool": [],
        },
    )

    assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "outer"
    assert _FakeRetriever.closes == 2

    retrieve_calls = [
        call for call in _FakeRetriever.calls if call["method"] == "retrieve"
    ]
    assert retrieve_calls
    assert all(call["filters"] is None for call in retrieve_calls)
    assert all(call["family_ids"] for call in retrieve_calls)
    assert all(call["top_k"] == 2 for call in retrieve_calls)
    assert not any(
        call["mode"] == "cards" and call["query"] == "No family query"
        for call in retrieve_calls
    )

    summary = payload["summary"]
    assert summary["scope"].startswith("planner_kg_fallback_proxy_only")
    assert summary["modes"]["legacy"]["has_kg_families_count"] == 2
    assert summary["modes"]["cards"]["has_kg_families_count"] == 1
    assert summary["modes"]["legacy"]["would_reach_kg_fallback_proxy_count"] == 2
    assert summary["modes"]["cards"]["would_reach_kg_fallback_proxy_count"] == 1
    assert summary["modes"]["legacy"]["raw_selected_modality_mismatch_count"] == 1
    assert summary["modes"]["legacy"]["selected_modality_mismatch_count"] == 0
    assert summary["modes"]["legacy"]["modality_rejected_total"] == 1
    assert summary["modes"]["cards"]["selected_modality_mismatch_count"] == 0
    assert summary["modes"]["legacy"]["candidate_empty_modality_total"] == 2
    assert summary["modes"]["legacy"]["selected_empty_modality_count"] == 1
    assert summary["comparison"]["selected_tool_diff_count"] == 2
    assert summary["comparison"]["any_mode_reaches_proxy_count"] == 2
    assert summary["comparison"]["both_modes_reach_proxy_count"] == 1

    predictions = [
        json.loads(line)
        for line in (tmp_path / "out" / "predictions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert {row["mode"] for row in predictions} == {"legacy", "cards"}
    legacy_meg = next(
        row
        for row in predictions
        if row["mode"] == "legacy" and row["task_id"] == "MEG-001"
    )
    assert legacy_meg["raw_selected_tool_id"] == "fmri_tool"
    assert legacy_meg["selected_tool_id"] == "empty_modality_tool"
    assert legacy_meg["modality_rejected_tool_ids"] == ["fmri_tool"]
    assert (tmp_path / "out" / "summary.json").exists()
    assert (tmp_path / "out" / "top_tool_diffs.jsonl").exists()
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "Planner Family Routing A/B" in report
    assert "KG-fallback proxy only" in report


def test_planner_family_ab_can_disable_gfs_for_routing_only_eval(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _FakeRetriever.calls = []
    _FakeRetriever.closes = 0
    monkeypatch.delenv("BR_TOOL_FAMILY_ROUTING_MODE", raising=False)

    labels = tmp_path / "labels.jsonl"
    _write_jsonl(labels, [{"task_id": "MEG-001", "query": "Estimate MEG connectivity"}])

    payload = harness.run_ab(
        labels_jsonl=labels,
        output_dir=tmp_path / "out",
        max_tasks=None,
        max_families=2,
        top_k=2,
        disable_gfs=True,
        retriever_factory=_fake_factory,
        tool_modalities={"fmri_tool": ["fmri"], "meg_tool": ["meg"]},
    )

    retrieve_calls = [
        call for call in _FakeRetriever.calls if call["method"] == "retrieve"
    ]
    assert retrieve_calls
    assert all(call["filters"] == {"disable_gfs": True} for call in retrieve_calls)
    assert payload["summary"]["disable_gfs"] is True
