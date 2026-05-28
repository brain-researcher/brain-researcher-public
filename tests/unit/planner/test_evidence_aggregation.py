"""Unit tests for evidence aggregation helpers."""

from __future__ import annotations

import pytest

from brain_researcher.services.agent.planner.evidence import aggregate_plan_job_evidence


def test_aggregate_plan_job_evidence_is_deterministic():
    job_payload = {
        "snapshot": {"intent": ["skull_strip"], "chosen_tool": "fsl.bet.run"},
        "context": {"pipeline": "skull_strip"},
        # Intentionally unsorted + duplicated
        "steps": [
            {"id": "s2", "tool": "tool.b", "params": {}},
            {"id": "s1", "tool": "tool.a", "params": {}},
            {"id": "s3", "tool": "tool.a", "params": {}},
        ],
    }
    workflow_result = {
        "state": "succeeded",
        "steps": [
            {"step_id": "s1", "tool": "tool.a", "status": "skipped"},
            {"step_id": "s2", "tool": "tool.b", "status": "skipped"},
        ],
    }

    records1 = aggregate_plan_job_evidence(
        job_payload=job_payload,
        workflow_result=workflow_result,
        duration_ms=1234,
        tool_versions={"tool.a": "v1", "tool.b": "v2"},
    )
    records2 = aggregate_plan_job_evidence(
        job_payload=job_payload,
        workflow_result=workflow_result,
        duration_ms=1234,
        tool_versions={"tool.a": "v1", "tool.b": "v2"},
    )

    assert records1 == records2
    assert [r.tool_id for r in records1] == ["tool.a", "tool.b"]
    assert all(r.task_family == "skull_strip" for r in records1)


def test_aggregate_plan_job_evidence_failure_category_is_stable():
    job_payload = {
        "snapshot": {"intent": ["connectivity"], "chosen_tool": "tool.timeout"},
        "context": {"pipeline": "connectivity"},
        "steps": [{"id": "s1", "tool": "tool.timeout", "params": {}}],
    }
    workflow_result = {
        "state": "failed",
        "error": "Timeout while executing tool",
        "steps": [{"step_id": "s1", "tool": "tool.timeout", "status": "error", "error": "timed out"}],
    }

    records = aggregate_plan_job_evidence(
        job_payload=job_payload,
        workflow_result=workflow_result,
        duration_ms=2000,
        tool_versions={"tool.timeout": "v1"},
    )

    assert len(records) == 1
    rec = records[0]
    assert rec.outcome == "fail"
    assert rec.failure_category  # should be populated


def test_aggregate_plan_job_evidence_propagates_loop_signals():
    job_payload = {
        "snapshot": {
            "intent": ["glm"],
            "chosen_tool": "glm.fitlins.run",
            "loop_signals": [
                {
                    "signal_type": "condition_tag",
                    "stage": "R1",
                    "condition_key": "task",
                    "condition_value": "motor",
                }
            ],
        },
        "context": {"pipeline": "glm"},
        "steps": [{"id": "s1", "tool": "glm.fitlins.run", "params": {}}],
    }
    workflow_result = {"state": "succeeded", "steps": []}

    records = aggregate_plan_job_evidence(
        job_payload=job_payload,
        workflow_result=workflow_result,
        duration_ms=1000,
        tool_versions={"glm.fitlins.run": "v1"},
    )

    assert len(records) == 1
    assert records[0].loop_signals
    assert records[0].loop_signals[0].signal_type == "condition_tag"


pytestmark = pytest.mark.unit
