"""Unit tests for evidence prior affecting unified planner ranking."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from brain_researcher.services.agent.planner.evidence import ToolEvidenceStats
from brain_researcher.services.agent.planner.selection import SelectionCandidate


class FakeEvidenceReader:
    def __init__(self, stats_by_tool_id):
        self._stats = stats_by_tool_id

    def read_stats(self, *, tool_versions, task_family, tool_ids):
        # Ignore versions for unit tests
        return {tid: self._stats[tid] for tid in tool_ids if tid in self._stats}


def test_evidence_prior_changes_ranking():
    """Higher prior success rate should increase rank when weights allow it."""

    class Tool:
        def __init__(self, tool_id: str):
            self.id = tool_id
            self.name = tool_id
            self.entrypoint = ""
            self.runtime_kind = "python"

    weights = {
        "intent_match": 0.0,
        "preflight": 0.0,
        "description": 0.0,
        "metadata": 0.0,
        "resource_fit": 0.0,
        "historical_quality": 1.0,
        "latency_pred": 0.0,
    }

    # Two candidates identical except tool id; base historical score neutral.
    cand_a = SelectionCandidate(
        tool=Tool("tool.a"),
        scoring_weights=weights,
        intent_match_score=0.0,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.5,
        latency_score=0.5,
    )
    cand_b = SelectionCandidate(
        tool=Tool("tool.b"),
        scoring_weights=weights,
        intent_match_score=0.0,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.5,
        latency_score=0.5,
    )

    reader = FakeEvidenceReader(
        {
            "tool.a": ToolEvidenceStats(success_count=1, fail_count=9),
            "tool.b": ToolEvidenceStats(success_count=9, fail_count=1),
        }
    )

    from brain_researcher.services.agent.planner.unified_planner import UnifiedPlanner

    planner = UnifiedPlanner(tool_retriever=None, evidence_reader=reader)

    with (
        patch(
            "brain_researcher.services.agent.planner.unified_planner.select_tools",
            return_value=[cand_a, cand_b],
        ),
        patch(
            "brain_researcher.services.agent.planner.unified_planner.match_intents",
            return_value=["skull_strip"],
        ),
    ):
        result = planner.plan(query="skull strip", modality=None, max_candidates=2)

    assert result.chosen_tool_id == "tool.b"
    assert result.candidates[0]["tool_id"] == "tool.b"


def test_evidence_prior_can_be_disabled(monkeypatch):
    """Disabling evidence prior should preserve the baseline ordering."""

    monkeypatch.setenv("BR_PLANNER_USE_EVIDENCE_PRIOR", "0")

    class Tool:
        def __init__(self, tool_id: str):
            self.id = tool_id
            self.name = tool_id
            self.entrypoint = ""
            self.runtime_kind = "python"

    weights = {
        "intent_match": 0.0,
        "preflight": 0.0,
        "description": 0.0,
        "metadata": 0.0,
        "resource_fit": 0.0,
        "historical_quality": 1.0,
        "latency_pred": 0.0,
    }

    cand_a = SelectionCandidate(
        tool=Tool("tool.a"),
        scoring_weights=weights,
        intent_match_score=0.0,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.5,
        latency_score=0.5,
    )
    cand_b = SelectionCandidate(
        tool=Tool("tool.b"),
        scoring_weights=weights,
        intent_match_score=0.0,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.5,
        latency_score=0.5,
    )

    reader = FakeEvidenceReader(
        {
            "tool.a": ToolEvidenceStats(success_count=1, fail_count=9),
            "tool.b": ToolEvidenceStats(success_count=9, fail_count=1),
        }
    )

    from brain_researcher.services.agent.planner.unified_planner import UnifiedPlanner

    planner = UnifiedPlanner(tool_retriever=None, evidence_reader=reader)

    with (
        patch(
            "brain_researcher.services.agent.planner.unified_planner.select_tools",
            return_value=[cand_a, cand_b],
        ),
        patch(
            "brain_researcher.services.agent.planner.unified_planner.match_intents",
            return_value=["skull_strip"],
        ),
    ):
        result = planner.plan(query="skull strip", modality=None, max_candidates=2)

    assert result.chosen_tool_id == "tool.a"
    assert result.candidates[0]["tool_id"] == "tool.a"
    assert "evidence_prior=disabled" in result.constraints_applied


pytestmark = pytest.mark.unit
