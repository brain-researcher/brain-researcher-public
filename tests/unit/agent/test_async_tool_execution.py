from __future__ import annotations

from types import SimpleNamespace

from brain_researcher.services.agent import web_service as ws


class _DummyJobService:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def create_async_tool_run(
        self,
        *,
        tool_id: str,
        params: dict,
        work_dir: str | None = None,
        output_dir: str | None = None,
        origin: str | None = None,
        run_id: str | None = None,
    ) -> dict:
        self.created.append(
            {
                "tool_id": tool_id,
                "params": params,
                "work_dir": work_dir,
                "output_dir": output_dir,
                "origin": origin,
                "run_id": run_id,
            }
        )
        return {
            "run_id": run_id or "job_async_tool_1",
            "status": "queued",
            "progress": 0.0,
            "run_dir": "/tmp/agent-run",
        }

    def create_async_plan_run(
        self,
        *,
        plan: dict,
        origin: str | None = None,
        run_id: str | None = None,
    ) -> dict:
        self.created.append({"plan": plan, "origin": origin, "run_id": run_id})
        return {
            "run_id": run_id or "job_plan_1",
            "status": "queued",
            "progress": 0.0,
            "run_dir": "/tmp/agent-plan-run",
        }

    def get_async_tool_status(self, run_id: str) -> dict | None:
        if run_id != "job_async_tool_1":
            return None
        return {
            "ok": True,
            "run_id": run_id,
            "status": "completed",
            "done": True,
            "tool_id": "python.test_tool",
            "params": {"x": 1},
            "work_dir": "/tmp/work",
            "output_dir": "/tmp/out",
            "preview": False,
            "origin": "mcp_delegate",
            "run_dir": "/tmp/agent-run",
            "provenance_path": "/tmp/agent-run/provenance.json",
            "result": {
                "status": "success",
                "error": None,
                "data": {"outputs": {"value": 7}},
                "metadata": {"run_id": run_id, "run_dir": "/tmp/agent-run"},
            },
        }


def test_tools_execute_async_round_trip(monkeypatch):
    job_service = _DummyJobService()
    client = ws.app.test_client()

    monkeypatch.setattr(
        "brain_researcher.services.agent.job_service.get_job_service",
        lambda: job_service,
    )
    monkeypatch.setattr(ws, "_is_tool_allowed_by_runtime_policy", lambda tool_id: True)

    response = client.post(
        "/tools/execute_async",
        json={
            "tool_id": "python.test_tool",
            "params": {"x": 1},
            "output_dir": "/tmp/out",
            "origin": "mcp_delegate",
        },
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body["ok"] is True
    assert body["run_id"] == "job_async_tool_1"
    assert body["status"] == "queued"
    assert body["execution_mode"] == "agent_async"
    assert body["status_url"] == "/tools/execute_async/job_async_tool_1"

    assert job_service.created == [
        {
            "tool_id": "python.test_tool",
            "params": {"x": 1},
            "work_dir": None,
            "output_dir": "/tmp/out",
            "origin": "mcp_delegate",
            "run_id": None,
        }
    ]

    status_resp = client.get(f"/tools/execute_async/{body['run_id']}")
    assert status_resp.status_code == 200
    status_body = status_resp.get_json()
    assert status_body["done"] is True
    assert status_body["status"] == "completed"
    assert status_body["result"]["status"] == "success"
    assert status_body["result"]["data"]["outputs"]["value"] == 7
    assert status_body["run_dir"] == "/tmp/agent-run"


def test_runs_execute_async_supports_plan_payload(monkeypatch):
    job_service = _DummyJobService()
    client = ws.app.test_client()

    monkeypatch.setattr(
        "brain_researcher.services.agent.job_service.get_job_service",
        lambda: job_service,
    )

    response = client.post(
        "/runs/execute_async",
        json={
            "execution_type": "plan",
            "run_id": "job_plan_1",
            "origin": "mcp_pipeline_execute",
            "plan": {
                "steps": [
                    {
                        "tool": "extract_timeseries",
                        "params": {"img": "x", "atlas": "y"},
                    }
                ]
            },
        },
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body["ok"] is True
    assert body["run_id"] == "job_plan_1"
    assert body["execution_type"] == "plan"
    assert body["execution_mode"] == "agent_async"
    assert job_service.created[-1] == {
        "plan": {
            "steps": [
                {
                    "tool": "extract_timeseries",
                    "params": {"img": "x", "atlas": "y"},
                }
            ]
        },
        "origin": "mcp_pipeline_execute",
        "run_id": "job_plan_1",
    }


def test_api_tools_run_alias_accepts_arguments_payload(monkeypatch):
    client = ws.app.test_client()
    calls: list[dict[str, object]] = []

    class _ToolResult:
        def model_dump(self):
            return {"status": "success", "data": {"ok": True}}

    def fake_execute_tool(tool_id, params, **kwargs):
        calls.append({"tool_id": tool_id, "params": params, **kwargs})
        return _ToolResult()

    monkeypatch.setenv("DISABLE_AUTH_FOR_DEV", "1")
    monkeypatch.setattr(ws, "_is_tool_allowed_by_runtime_policy", lambda tool_id: True)
    monkeypatch.setattr(
        ws,
        "_resolve_runtime_tool_instance",
        lambda tool_id: (tool_id, SimpleNamespace()),
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.executor.execute_tool",
        fake_execute_tool,
    )

    response = client.post(
        "/api/tools/run",
        json={
            "tool": "workflow_rest_connectome_e2e",
            "arguments": {"img": "bold.nii.gz"},
        },
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"
    assert calls == [
        {
            "tool_id": "workflow_rest_connectome_e2e",
            "params": {"img": "bold.nii.gz"},
            "work_dir": None,
            "output_dir": None,
            "preview": False,
        }
    ]
