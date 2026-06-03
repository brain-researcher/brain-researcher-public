"""Unit tests for contrast text Task->Construct->Map orchestration."""

from __future__ import annotations

from typing import Any

import pytest

from brain_researcher.services.br_kg.niclip.contrast_text_orchestrator import (
    ContrastTextToPredictedMapOrchestrator,
)


class _DummyEngine:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def search(self, _query: str, top_k: int = 10):
        return self._rows[:top_k]

    def status(self):
        return {"status": "healthy", "mode": "embedding_only"}


class _DummyTaskMapper:
    concept_to_process = {"working memory": "ctp_C3", "attention": "ctp_C3"}

    def get_task_concepts(self, task_name: str):
        if "n-back" in task_name.lower():
            return ["working memory", "attention"]
        return []

    def get_primary_process(self, _task_name: str):
        return "ctp_C3"

    def get_process_name(self, _process_id: str):
        return "Cognitive Control"


def test_orchestrate_success(monkeypatch):
    def _fake_mapping(keyword: str, threshold: float = 3.0):
        assert threshold == 3.0
        if keyword == "working memory":
            return {
                "term_used": "working memory",
                "activation_maps": [object()],
                "n_studies": 12,
                "n_coords": 2,
                "coordinates": [{"x": 40, "y": 24, "z": 32}, {"x": -42, "y": 22, "z": 30}],
                "threshold_count": 3.0,
            }
        return {"activation_maps": []}

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.niclip.contrast_text_orchestrator.get_neurosynth_mapping",
        _fake_mapping,
    )

    orchestrator = ContrastTextToPredictedMapOrchestrator(
        engine=_DummyEngine([{"item": "n-back", "similarity": 0.91}]),
        task_mapper=_DummyTaskMapper(),
    )
    result = orchestrator.orchestrate(contrast_text="2-back > 0-back")

    assert result["task_predictions"][0]["task"] == "n-back"
    assert result["constructs"][0]["concept"] == "working memory"
    assert result["predicted_map"]["map_generated"] is True
    assert result["predicted_map"]["selected_term"] == "working memory"
    assert result["coordinate_to_concept_args"]["coordinates"][0] == [40.0, 24.0, 32.0]


def test_orchestrate_tries_next_construct_when_first_fails(monkeypatch):
    calls: list[str] = []

    def _fake_mapping(keyword: str, threshold: float = 3.0):
        calls.append(keyword)
        if keyword == "attention":
            return {
                "term_used": "attention",
                "activation_maps": [object()],
                "n_studies": 5,
                "n_coords": 1,
                "coordinates": [{"x": 1, "y": 2, "z": 3}],
                "threshold_count": threshold,
            }
        return {"activation_maps": []}

    monkeypatch.setattr(
        "brain_researcher.services.br_kg.niclip.contrast_text_orchestrator.get_neurosynth_mapping",
        _fake_mapping,
    )

    orchestrator = ContrastTextToPredictedMapOrchestrator(
        engine=_DummyEngine([{"item": "n-back", "similarity": 0.8}]),
        task_mapper=_DummyTaskMapper(),
    )
    result = orchestrator.orchestrate(
        contrast_text="hard > easy",
        top_k_constructs=2,
        top_k_map_terms=2,
    )

    assert calls[:2] == ["working memory", "attention"]
    assert result["predicted_map"]["map_generated"] is True
    assert result["predicted_map"]["selected_term"] == "attention"


def test_orchestrate_requires_contrast_text():
    orchestrator = ContrastTextToPredictedMapOrchestrator(
        engine=_DummyEngine([{"item": "n-back", "similarity": 0.8}]),
        task_mapper=_DummyTaskMapper(),
    )

    with pytest.raises(ValueError, match="contrast_text is required"):
        orchestrator.orchestrate(contrast_text="")
