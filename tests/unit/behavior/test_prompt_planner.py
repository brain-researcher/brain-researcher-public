from __future__ import annotations

import pytest

from brain_researcher.behavior.planner import plan_task_from_prompt


def test_plan_task_from_prompt_matches_nback_and_extracts_scanner_profile():
    result = plan_task_from_prompt(
        "2-back letter task, 6 min, TR=2s, 4 dummy scans",
        raw_candidates=[
            {"label": "stop task", "score": 0.0, "engine": "niclip"},
            {"label": "letter n-back task", "score": 0.74, "engine": "sbert"},
        ],
    )
    assert result["resolution"] == "matched"
    assert result["paradigm"] == "n_back"
    assert result["scanner_profile"] == {
        "planned_duration_sec": 360.0,
        "tr_sec": 2.0,
        "dummy_scans": 4,
        "n_volumes": 184,
    }
    assert result["overrides"]["conditions"] == ["2-back"]
    assert result["overrides"]["extras"]["stimulus_variant"] == "letters"


def test_plan_task_from_prompt_returns_ambiguous_with_question():
    result = plan_task_from_prompt(
        "cognitive control task",
        raw_candidates=[
            {"label": "go/no-go task", "score": 0.7, "engine": "sbert"},
            {"label": "flanker task", "score": 0.8, "engine": "sbert"},
        ],
    )
    assert result["resolution"] == "ambiguous"
    assert result["paradigm"] is None
    assert result["clarifying_questions"]


def test_plan_task_from_prompt_abstains_on_novel_prompt():
    result = plan_task_from_prompt(
        "novel interoceptive breathing-switch task",
        raw_candidates=[
            {"label": "emotion regulation task", "score": 0.8, "engine": "sbert"},
        ],
    )
    assert result["resolution"] == "abstain"
    assert result["paradigm"] is None
    assert result["reason"] == "no_supported_paradigm_match"


def test_plan_task_from_prompt_rejects_empty_query():
    with pytest.raises(ValueError):
        plan_task_from_prompt("  ", raw_candidates=[])
