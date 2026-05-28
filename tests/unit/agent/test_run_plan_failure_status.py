from __future__ import annotations

from types import SimpleNamespace

from brain_researcher.services.agent import web_service as ws
from brain_researcher.services.shared.planner.models import Plan, RunPlanRequest


def test_execute_plan_with_streaming_marks_plan_failed(monkeypatch, tmp_path):
    class FakeExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def execute_with_timeout(self, *args, **kwargs):
            return SimpleNamespace(status="error", error="File not found: bold.nii.gz")

    plan = Plan.model_validate(
        {
            "plan_id": "plan_failure_status",
            "version": 1,
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "resolvable": True,
            "dag": {
                "steps": [
                    {
                        "id": "step-001",
                        "tool": "workflow_rest_connectome_e2e",
                        "params": {"img": "bold.nii.gz"},
                        "runtime_kind": "python",
                    }
                ],
                "artifacts": [],
            },
        }
    )
    run_request = RunPlanRequest(
        plan_id=plan.plan_id,
        version=plan.version,
        por_token="por-test-token",
        plan=plan,
    )

    monkeypatch.setenv("BR_RUN_ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setattr(ws, "get_tool_by_id", lambda tool_id: SimpleNamespace())
    monkeypatch.setattr(
        ws,
        "_resolve_runtime_tool_instance",
        lambda tool_id: (tool_id, SimpleNamespace(get_tool_name=lambda: tool_id)),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.tool_executor.BudgetedToolExecutor",
        FakeExecutor,
    )
    monkeypatch.setattr(ws, "_get_plan_memory", lambda: None)

    with ws.app.test_request_context("/agent/run_plan"):
        payload = "".join(ws._execute_plan_with_streaming(run_request))

    assert "event: step_failed" in payload
    assert "event: plan_failed" in payload
    assert "File not found: bold.nii.gz" in payload
    assert "event: plan_completed" not in payload
