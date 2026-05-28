import json
from pathlib import Path

from brain_researcher.services.orchestrator.trace import (
    build_atif_trajectory,
    log_trace_event,
    write_trajectory_json,
)


def test_trace_jsonl_is_event_log(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    out = log_trace_event(
        run_dir,
        run_id="run-1",
        event_type="step_started",
        payload={"step_id": "s1", "tool": "demo.tool"},
        timestamp="2026-01-01T00:00:00Z",
    )
    assert out is not None
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["schema_version"] == "analysis-stream-event-v1"
    assert obj["ids"]["run_id"] == "run-1"
    assert obj["event_type"] == "stage"
    assert obj["timestamp"] == "2026-01-01T00:00:00Z"
    assert obj["payload"]["status"] == "started"
    assert obj["payload"]["stage_id"] == "s1"
    assert obj["payload"]["tool_id"] == "demo.tool"


def test_write_trajectory_json_atif(tmp_path: Path):
    workflow_steps = [
        {
            "step_id": "s1",
            "tool": "demo.tool",
            "status": "succeeded",
            "duration_ms": 123,
            "violations": [],
            "result": {"ok": True},
        }
    ]
    plan_steps = [{"id": "s1", "tool": "demo.tool", "params": {"x": 1}}]
    traj = build_atif_trajectory(
        session_id="run-123",
        user_message="Run the demo pipeline",
        workflow_steps=workflow_steps,
        plan_steps=plan_steps,
        model_name="gpt-test",
        extra={"job_id": "job-1"},
    )
    path = write_trajectory_json(tmp_path, traj)
    assert path is not None

    obj = json.loads(path.read_text(encoding="utf-8"))
    assert obj["schema_version"] == "ATIF-v1.4"
    assert obj["session_id"] == "run-123"
    assert obj["agent"]["model_name"] == "gpt-test"
    assert [s["step_id"] for s in obj["steps"]] == [1, 2]
    assert obj["steps"][0]["source"] == "user"
    assert obj["steps"][1]["source"] == "agent"
    assert obj["steps"][1]["tool_calls"][0]["function_name"] == "demo.tool"
    assert obj["steps"][1]["tool_calls"][0]["arguments"] == {"x": 1}
    assert obj["final_metrics"]["total_steps"] == 2
