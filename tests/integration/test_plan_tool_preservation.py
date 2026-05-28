"""Integration checks for plan tool-id preservation across submission surfaces."""

from __future__ import annotations

import json
from types import SimpleNamespace

from brain_researcher.services.agent.web_service import app as agent_app
from brain_researcher.services.mcp import server as mcp_server
from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.observation import load_or_build_observation


def test_ui_plan_preserves_tool_ids(monkeypatch):
    from brain_researcher.services.agent import agent_auth, ui_api

    captured_plan: dict[str, object] = {}

    class _FakeJobService:
        def create_run(self, plan, user_id, thread_id=None):
            captured_plan["plan"] = plan
            captured_plan["user_id"] = user_id
            captured_plan["thread_id"] = thread_id
            return {
                "run_id": "job_ui_preserve_001",
                "status": "queued",
                "plan": plan,
                "user_id": user_id,
                "thread_id": thread_id,
            }

    monkeypatch.setattr(ui_api, "_get_job_service", lambda: _FakeJobService())
    monkeypatch.setattr(
        agent_auth,
        "get_current_user",
        lambda _request: SimpleNamespace(id="user_ui_1"),
    )

    client = agent_app.test_client()
    plan_payload = {
        "type": "dataset_analysis",
        "steps": [
            {"tool": "workflow_preprocessing_qc", "args": {"dataset_id": "ds:manual:abide"}},
            {"tool": "run_mriqc_workflow", "args": {"bids_dir": "/data/bids"}},
        ],
    }
    response = client.post("/api/runs", json={"plan": plan_payload, "thread_id": "thread-1"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["plan"]["steps"][0]["tool"] == "workflow_preprocessing_qc"
    assert body["plan"]["steps"][1]["tool"] == "run_mriqc_workflow"
    assert captured_plan["plan"] == plan_payload


def test_mcp_plan_preserves_tool_ids(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "_preflight_tool_call",
        lambda tool_id, params, **_: (SimpleNamespace(name=tool_id), []),
    )
    monkeypatch.setattr(mcp_server, "_new_run_id", lambda: "run_test_preserve")

    plan = {
        "steps": [
            {"tool": "run_bids_app", "params": {"app": "fmriprep"}},
            {"tool": "run_mriqc_workflow", "params": {"bids_dir": "/data/bids"}},
        ]
    }
    result = mcp_server.pipeline_plan_validate(plan)
    assert result["ok"] is True
    tools = [step["tool"] for step in result["normalized_plan"]["steps"]]
    assert tools == ["run_bids_app", "run_mriqc_workflow"]


def test_observation_records_executed_tools(tmp_path):
    payload = {
        "plan": {
            "dag": {
                "steps": [
                    {"id": "s1", "tool": "run_bids_app", "params": {}},
                    {"id": "s2", "tool": "run_mriqc_workflow", "params": {}},
                ]
            }
        }
    }
    record = JobRecord(
        job_id="job_observation_tools_001",
        kind="plan_execution",
        payload_json=json.dumps(payload),
        state=JobState.SUCCEEDED.value,
        run_dir=str(tmp_path),
    )

    spec = load_or_build_observation(record)
    assert spec is not None
    assert spec.run_card is not None
    tool_names = [tool.get("name") for tool in spec.run_card.tools]
    assert tool_names == ["run_bids_app", "run_mriqc_workflow"]

