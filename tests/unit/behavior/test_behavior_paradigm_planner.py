from __future__ import annotations

import pytest

from brain_researcher.services.tools.behavior_paradigm_planner import (
    BehaviorParadigmPlannerTool,
    record_research_event,
)


def test_record_research_event_none_sink():
    event = record_research_event(
        None, kind="paradigm_resolved", content="hello", context={"a": 1}, tags=["t"]
    )
    assert set(event.keys()) == {"kind", "content", "context", "tags", "ts"}
    assert event["kind"] == "paradigm_resolved"
    assert event["content"] == "hello"
    assert event["context"] == {"a": 1}
    assert event["tags"] == ["t"]
    assert isinstance(event["ts"], str) and event["ts"]


def test_record_research_event_list_sink():
    sink: list[dict] = []
    event = record_research_event(sink, kind="plan_proposed", content="c")
    assert len(sink) == 1
    assert sink[0] is event
    assert sink[0]["kind"] == "plan_proposed"


def test_record_research_event_callable_sink_exception_swallowed():
    def raiser(_e):
        raise RuntimeError("boom")

    # Must not raise
    event = record_research_event(raiser, kind="k", content="c")
    assert event["kind"] == "k"


def test_planner_with_stub_matcher():
    class StubMatcher:
        def match_candidates(self, query: str, top_k: int = 5):
            return [
                {"label": "n-back", "score": 1.0, "engine": "exact"},
                {"label": "digit span", "score": 0.65, "engine": "sbert"},
            ]

    tool = BehaviorParadigmPlannerTool()
    result = tool._run(query="two-back working memory", task_matcher=StubMatcher())

    assert result.status == "success"
    data = result.data
    assert data["resolution"] == "matched"
    assert data["paradigm"] == "n_back"
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["label"] == "n-back"
    assert data["candidates"][0]["paradigm"] == "n_back"

    plan = data["plan"]
    assert plan["ingest"]["tool"] == "behavior.ingest_taps"
    assert plan["qc"]["tool"] == "behavior.qc_scan"
    assert plan["export"]["tool"] == "behavior.export_bids"
    assert plan["qc"]["config"]["policy_path"].endswith("behavior_outlier_policy.yaml")
    assert plan["export"]["config"]["drop_excluded"] is True

    kinds = [e["kind"] for e in data["events"]]
    assert "paradigm_resolved" in kinds
    assert "plan_proposed" in kinds

    assert any("top_paradigm" in n for n in data["notes"])


def test_planner_matcher_unavailable():
    class BadMatcher:
        def match_candidates(self, query: str, top_k: int = 5):
            raise RuntimeError("boom")

    tool = BehaviorParadigmPlannerTool()
    result = tool._run(query="flanker", task_matcher=BadMatcher())

    assert result.status == "success"
    assert result.data["resolution"] == "matched"
    assert result.data["paradigm"] == "flanker"
    assert any("task_matcher_unavailable" in n for n in result.data["notes"])


def test_planner_respects_drop_excluded_flag():
    class StubMatcher:
        def match_candidates(self, query: str, top_k: int = 5):
            return []

    tool = BehaviorParadigmPlannerTool()
    result = tool._run(
        query="go/no-go task", task_matcher=StubMatcher(), drop_excluded=False
    )
    assert result.status == "success"
    assert result.data["paradigm"] == "go_no_go"
    assert result.data["plan"]["export"]["config"]["drop_excluded"] is False


def test_planner_honors_expected_rt_hint():
    class StubMatcher:
        def match_candidates(self, query: str, top_k: int = 5):
            return []

    tool = BehaviorParadigmPlannerTool()
    result = tool._run(
        query="flanker", task_matcher=StubMatcher(), expected_rt_sec=0.45
    )
    assert result.status == "success"
    assert any("expected_rt_hint_sec" in n for n in result.data["notes"])


def test_planner_emits_clarifying_questions_for_ambiguous_prompt():
    class StubMatcher:
        def match_candidates(self, query: str, top_k: int = 5):
            return [
                {"label": "go/no-go task", "score": 0.7, "engine": "sbert"},
                {"label": "flanker task", "score": 0.8, "engine": "sbert"},
            ]

    tool = BehaviorParadigmPlannerTool()
    result = tool._run(query="cognitive control task", task_matcher=StubMatcher())
    assert result.status == "success"
    assert result.data["resolution"] == "ambiguous"
    assert result.data["clarifying_questions"]


def test_planner_rejects_empty_query_via_schema():
    from brain_researcher.services.tools.behavior_paradigm_planner import (
        BehaviorParadigmPlanArgs,
    )

    with pytest.raises(Exception):
        BehaviorParadigmPlanArgs(query="   ")
