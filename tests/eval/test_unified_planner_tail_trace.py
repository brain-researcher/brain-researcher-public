"""Tests for the UnifiedPlanner tail-frequency trace harness."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from brain_researcher.services.agent.planner.selection import SelectionCandidate

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "unified_planner_tail_trace.py"
SPEC = importlib.util.spec_from_file_location("unified_planner_tail_trace", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
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
        return [f"{self.mode}.connectivity"]

    def retrieve_tools(
        self,
        query: str,
        family_ids: list[str] | None = None,
        top_k: int = 20,
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
        if "MEG" in query:
            return [_Match("fmri_tool", 1.0), _Match("meg_tool", 0.9)]
        return [_Match("kg_side_tool", 0.8)]

    def close(self) -> None:
        _FakeRetriever.closes += 1


def _fake_factory() -> _FakeRetriever:
    return _FakeRetriever()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _tool(tool_id: str, modality: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=tool_id,
        name=tool_id,
        modality=modality,
        modalities=[modality] if modality else [],
        entrypoint="",
        package=tool_id,
        capabilities=[],
        intents=[],
        constraints={},
    )


def _candidate(tool_id: str) -> SelectionCandidate:
    weights = {
        "intent_match": 1.0,
        "preflight": 0.0,
        "description": 0.0,
        "metadata": 0.0,
        "resource_fit": 0.0,
        "historical_quality": 0.0,
        "latency_pred": 0.0,
    }
    return SelectionCandidate(
        tool=_tool(tool_id, "fmri"),
        scoring_weights=weights,
        intent_match_score=1.0,
        preflight_passed=True,
        source="catalog",
    )


def _select_tools(**kwargs: Any) -> list[SelectionCandidate]:
    query = str(kwargs.get("query") or "")
    if "Base" in query:
        return [_candidate("catalog_tool")]
    return []


def _fake_get_tool_by_id(tool_id: str) -> SimpleNamespace | None:
    tools = {
        "catalog_tool": _tool("catalog_tool", "fmri"),
        "kg_side_tool": _tool("kg_side_tool", "fmri"),
        "fmri_tool": _tool("fmri_tool", "fmri"),
        "meg_tool": _tool("meg_tool", "meg"),
    }
    return tools.get(tool_id)


def test_family_routing_mode_restores_environment(monkeypatch: Any) -> None:
    monkeypatch.setenv("BR_TOOL_FAMILY_ROUTING_MODE", "outer")

    with harness._family_routing_mode("cards"):
        assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "cards"

    assert os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] == "outer"


def test_tail_trace_records_base_and_kg_only_fallback_branches(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _FakeRetriever.calls = []
    _FakeRetriever.closes = 0
    monkeypatch.setenv("BR_PLANNER_USE_CAPABILITY_PRIOR", "0")
    monkeypatch.setenv("BR_PLANNER_USE_EVIDENCE_PRIOR", "0")
    monkeypatch.setattr(harness.planner_module, "get_tool_by_id", _fake_get_tool_by_id)

    labels = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "BASE-001",
                "query": "Base fMRI catalog candidate",
                "exact_labels": {"expected_tool_ids": ["catalog_tool"]},
            },
            {
                "task_id": "KG-001",
                "query": "Estimate source-space connectivity from MEG epochs",
                "exact_labels": {"acceptable_tool_ids": ["meg_tool"]},
            },
        ],
    )

    payload = harness.run_tail_trace(
        labels_jsonl=labels,
        output_dir=tmp_path / "out",
        max_tasks=None,
        mode="both",
        max_candidates=5,
        max_families=2,
        retriever_top_k=3,
        retriever_factory=_fake_factory,
        select_tools_func=_select_tools,
        tool_modalities={
            "catalog_tool": ["fmri"],
            "kg_side_tool": ["fmri"],
            "fmri_tool": ["fmri"],
            "meg_tool": ["meg"],
        },
    )

    assert _FakeRetriever.closes == 2
    assert (tmp_path / "out" / "summary.json").exists()
    assert (tmp_path / "out" / "predictions.jsonl").exists()
    assert (tmp_path / "out" / "report.md").exists()

    summary = payload["summary"]
    assert summary["scope"].startswith("unified_planner_plan_path_tail_trace")
    assert summary["overall"]["task_count"] == 4
    assert summary["overall"]["base_candidate_case_count"] == 2
    assert summary["overall"]["kg_family_case_count"] == 4
    assert summary["overall"]["kg_only_fallback_case_count"] == 2
    assert summary["overall"]["selected_modality_mismatch_count"] == 0

    rows = payload["predictions"]
    base_legacy = next(
        row for row in rows if row["task_id"] == "BASE-001" and row["mode"] == "legacy"
    )
    assert base_legacy["base_select_tools_produced_candidates"] is True
    assert base_legacy["base_top_tool_ids"] == ["catalog_tool"]
    assert base_legacy["kg_only_fallback_used"] is False
    assert base_legacy["chosen_tool_id"] == "catalog_tool"
    assert base_legacy["candidate_source_counts"] == {"catalog": 1}

    kg_cards = next(
        row for row in rows if row["task_id"] == "KG-001" and row["mode"] == "cards"
    )
    assert kg_cards["base_select_tools_produced_candidates"] is False
    assert kg_cards["kg_families"] == ["cards.connectivity"]
    assert kg_cards["kg_only_fallback_used"] is True
    assert kg_cards["kg_raw_tool_ids"] == ["fmri_tool", "meg_tool"]
    assert kg_cards["chosen_tool_id"] == "meg_tool"
    assert kg_cards["selected_modalities"] == ["meg"]
    assert kg_cards["selected_modality_mismatch"] is False
    assert "kg_modality_gate=meg" in kg_cards["constraints_applied"]
    assert any(
        item.startswith("kg_modality_rejected=fmri_tool")
        for item in kg_cards["constraints_applied"]
    )
    assert kg_cards["routing_diagnostics"]["candidate_source_counts"] == {"br_kg": 1}

    retrieve_calls = [
        call for call in _FakeRetriever.calls if call["method"] == "retrieve"
    ]
    assert retrieve_calls
    assert all(call["top_k"] == 3 for call in retrieve_calls)


def test_tail_trace_disable_gfs_passes_retriever_filter(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _FakeRetriever.calls = []
    _FakeRetriever.closes = 0
    monkeypatch.setenv("BR_PLANNER_USE_CAPABILITY_PRIOR", "0")
    monkeypatch.setenv("BR_PLANNER_USE_EVIDENCE_PRIOR", "0")
    monkeypatch.setattr(harness.planner_module, "get_tool_by_id", _fake_get_tool_by_id)

    labels = tmp_path / "labels.jsonl"
    _write_jsonl(
        labels,
        [{"task_id": "BASE-001", "query": "Base fMRI catalog candidate"}],
    )

    payload = harness.run_tail_trace(
        labels_jsonl=labels,
        output_dir=tmp_path / "out",
        max_tasks=None,
        mode="legacy",
        disable_gfs=True,
        retriever_factory=_fake_factory,
        select_tools_func=_select_tools,
        tool_modalities={"catalog_tool": ["fmri"], "kg_side_tool": ["fmri"]},
    )

    retrieve_calls = [
        call for call in _FakeRetriever.calls if call["method"] == "retrieve"
    ]
    assert retrieve_calls
    assert all(call["filters"] == {"disable_gfs": True} for call in retrieve_calls)
    assert payload["predictions"][0]["kg_retrieve_filters"] == [{"disable_gfs": True}]
    assert payload["summary"]["disable_gfs"] is True
