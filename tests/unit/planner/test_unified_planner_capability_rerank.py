"""Unit tests for capability-prediction-aware reranking in UnifiedPlanner."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from brain_researcher.services.agent.planner.capability_predictor import (
    CapabilityPrediction,
)
from brain_researcher.services.agent.planner.selection import SelectionCandidate
from brain_researcher.services.agent.planner.unified_planner import UnifiedPlanner


class _Tool:
    def __init__(self, tool_id: str, capabilities: list[str]) -> None:
        self.id = tool_id
        self.name = tool_id
        self.entrypoint = ""
        self.runtime_kind = "python"
        self.package = "python"
        self.capabilities = capabilities
        self.intents: list[str] = []


class _NullEvidenceReader:
    def read_stats(self, **kwargs):  # noqa: D401 - test stub
        return {}


def test_capability_prediction_can_override_base_score(monkeypatch):
    monkeypatch.setenv("BR_CAPABILITY_RERANK_WEIGHT", "1.0")

    weights = {
        "intent_match": 1.0,
        "preflight": 0.0,
        "description": 0.0,
        "metadata": 0.0,
        "resource_fit": 0.0,
        "historical_quality": 0.0,
        "latency_pred": 0.0,
    }
    cand_a = SelectionCandidate(
        tool=_Tool("tool.a", ["visualization"]),
        scoring_weights=weights,
        intent_match_score=0.95,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.0,
        latency_score=0.0,
    )
    cand_b = SelectionCandidate(
        tool=_Tool("tool.b", ["quality_control"]),
        scoring_weights=weights,
        intent_match_score=0.10,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.0,
        latency_score=0.0,
    )

    prediction = CapabilityPrediction(
        predicted_capabilities=["quality_control"],
        predicted_intents=["quality_control"],
        direct_intents=["quality_control"],
        matched_crosswalk_keys=["quality_control_tool"],
        confidence=1.0,
        debug={},
    )
    planner = UnifiedPlanner(tool_retriever=None, evidence_reader=_NullEvidenceReader())

    with (
        patch(
            "brain_researcher.services.agent.planner.unified_planner.select_tools",
            return_value=[cand_a, cand_b],
        ),
        patch(
            "brain_researcher.services.agent.planner.unified_planner.predict_capabilities",
            return_value=prediction,
        ),
    ):
        result = planner.plan(query="run MRIQC", modality="fmri", max_candidates=2)

    assert result.chosen_tool_id == "tool.b"
    assert result.predicted_capabilities == ["quality_control"]
    assert result.candidates[0]["tool_id"] == "tool.b"
    assert (
        result.candidates[0]["capability_match_score"]
        > result.candidates[1]["capability_match_score"]
    )


def test_capability_prior_can_be_disabled(monkeypatch):
    monkeypatch.setenv("BR_CAPABILITY_RERANK_WEIGHT", "1.0")
    monkeypatch.setenv("BR_PLANNER_USE_CAPABILITY_PRIOR", "0")

    weights = {
        "intent_match": 1.0,
        "preflight": 0.0,
        "description": 0.0,
        "metadata": 0.0,
        "resource_fit": 0.0,
        "historical_quality": 0.0,
        "latency_pred": 0.0,
    }
    cand_a = SelectionCandidate(
        tool=_Tool("tool.a", ["visualization"]),
        scoring_weights=weights,
        intent_match_score=0.95,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.0,
        latency_score=0.0,
    )
    cand_b = SelectionCandidate(
        tool=_Tool("tool.b", ["quality_control"]),
        scoring_weights=weights,
        intent_match_score=0.10,
        preflight_passed=True,
        description_score=0.0,
        metadata_score=0.0,
        resource_fit_score=0.0,
        historical_quality_score=0.0,
        latency_score=0.0,
    )

    prediction = CapabilityPrediction(
        predicted_capabilities=["quality_control"],
        predicted_intents=["quality_control"],
        direct_intents=["quality_control"],
        matched_crosswalk_keys=["quality_control_tool"],
        confidence=1.0,
        debug={},
    )
    planner = UnifiedPlanner(tool_retriever=None, evidence_reader=_NullEvidenceReader())

    with (
        patch(
            "brain_researcher.services.agent.planner.unified_planner.select_tools",
            return_value=[cand_a, cand_b],
        ),
        patch(
            "brain_researcher.services.agent.planner.unified_planner.predict_capabilities",
            return_value=prediction,
        ),
    ):
        result = planner.plan(query="run MRIQC", modality="fmri", max_candidates=2)

    assert result.chosen_tool_id == "tool.a"
    assert result.candidates[0]["tool_id"] == "tool.a"
    assert "capability_prior=disabled" in result.constraints_applied


pytestmark = pytest.mark.unit
