from brain_researcher.services.agent.planner.failure_neo4j import FailureKGRecord
from brain_researcher.services.agent.planner.failure_neo4j import (
    is_failure_agg_writeback_enabled,
)


def test_failure_record_to_row_includes_new_fields():
    rec = FailureKGRecord(
        failure_id="fid1",
        plan_id="pid1",
        step_id="s1",
        tool_id="tool.a",
        tool_version_id="tool.a@v1",
        error_category="tool",
        recovery_action=None,
        is_retryable=True,
        error_message="boom",
        error_taxonomy={"category": "tool"},
        recovery_actions=None,
        attempt=1,
        max_attempts=2,
        recovered=False,
        created_at=123,
        dataset_id="ds:openneuro:ds000001",
        task_family="glm",
        run_id="run1",
    )
    row = rec.to_row()
    assert row["tool_version_id"] == "tool.a@v1"
    assert row["dataset_id"] == "ds:openneuro:ds000001"
    assert row["task_family"] == "glm"
    assert row["run_id"] == "run1"


def test_failure_agg_flag(monkeypatch):
    monkeypatch.setenv("BR_KG_FAILURE_AGG_WRITEBACK", "1")
    assert is_failure_agg_writeback_enabled()
    monkeypatch.setenv("BR_KG_FAILURE_AGG_WRITEBACK", "false")
    assert not is_failure_agg_writeback_enabled()
