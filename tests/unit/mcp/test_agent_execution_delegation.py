from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _stub_toolspec_registry(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda tool_id: ToolSpec(
            name=tool_id,
            description="stub",
            backend="python",
            python_class="json:loads",
            required=["img", "atlas"] if tool_id == "extract_timeseries" else [],
        ),
    )
    monkeypatch.setattr(srv, "load_orchestration_workflows", lambda: [])


def _configure_agent_delegation_env(monkeypatch, tmp_path: Path) -> None:
    from brain_researcher.services.mcp import server as srv

    allowed_root = tmp_path.resolve()
    monkeypatch.setattr(srv, "RUN_ROOT", allowed_root)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [allowed_root])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"extract_timeseries"})
    monkeypatch.setattr(srv, "AGENT_DELEGATED_EXECUTION_ENABLED", True)


def test_behavior_generate_psyflow_task_delegates_to_agent(monkeypatch, tmp_path):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_agent_delegation_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        srv,
        "TOOL_EXECUTE_ALLOWLIST",
        {"behavior.generate_psyflow_task"},
    )
    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda tool_id: ToolSpec(
            name=tool_id,
            description="stub",
            backend="python",
            python_class="json:loads",
            required=["spec", "out_dir", "review"]
            if tool_id == "behavior.generate_psyflow_task"
            else [],
        ),
    )

    captured: dict[str, object] = {}

    def _fake_delegate(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "run_id": kwargs["run_id"],
            "status": "queued",
            "run_dir": "/agent/runs/delegated-behavior-task",
        }

    monkeypatch.setattr(srv, "_delegate_execution_to_agent", _fake_delegate)

    out_dir = tmp_path / "bundle"
    resp = srv.tool_execute(
        "behavior.generate_psyflow_task",
        params={
            "spec": {"schema_id": "behavior-task-spec-v1"},
            "out_dir": str(out_dir),
            "review": {"spec_digest": "a" * 64, "approved": True},
        },
        output_dir=str(tmp_path / "artifacts"),
    )

    assert resp["ok"] is True
    assert resp["execution_mode"] == "agent_delegated"
    assert resp["resolved_tool_id"] == "behavior.generate_psyflow_task"
    run_id = resp["run_id"]
    assert captured == {
        "run_id": run_id,
        "execution_type": "tool",
        "tool_id": "behavior.generate_psyflow_task",
        "params": {
            "spec": {"schema_id": "behavior-task-spec-v1"},
            "out_dir": str(out_dir),
            "review": {"spec_digest": "a" * 64, "approved": True},
        },
        "work_dir": None,
        "output_dir": str(tmp_path / "artifacts"),
    }

    local_run_dir = tmp_path / "runs" / run_id
    provenance = json.loads(
        (local_run_dir / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["delegated_execution"]["backend"] == "agent"
    assert provenance["delegated_execution"]["execution_type"] == "tool"
    assert provenance["request"]["output_dir"] == str(tmp_path / "artifacts")


def test_tool_execute_delegates_to_agent_run_facade(monkeypatch, tmp_path):
    from brain_researcher.services.mcp import server as srv

    _configure_agent_delegation_env(monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    def _fake_delegate(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "run_id": kwargs["run_id"],
            "status": "queued",
            "run_dir": "/agent/runs/delegated-tool",
        }

    monkeypatch.setattr(srv, "_delegate_execution_to_agent", _fake_delegate)

    resp = srv.tool_execute("extract_timeseries", params={"img": "x", "atlas": "y"})

    assert resp["ok"] is True
    assert resp["execution_mode"] == "agent_delegated"
    run_id = resp["run_id"]
    assert captured == {
        "run_id": run_id,
        "execution_type": "tool",
        "tool_id": "extract_timeseries",
        "params": {"img": "x", "atlas": "y"},
        "work_dir": None,
        "output_dir": None,
    }

    local_run_dir = tmp_path / "runs" / run_id
    provenance = json.loads(
        (local_run_dir / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["delegated_execution"]["backend"] == "agent"
    assert provenance["delegated_execution"]["execution_type"] == "tool"

    def _fake_proxy(
        run_id_arg: str, *, suffix: str = "", method: str = "GET", payload=None
    ):
        assert run_id_arg == run_id
        assert method == "GET"
        assert payload is None
        if suffix == "":
            return {
                "ok": True,
                "run_id": run_id,
                "status": "completed",
                "progress": 1.0,
                "started_at": "2026-03-15T01:00:00Z",
                "finished_at": "2026-03-15T01:00:02Z",
                "run_dir": "/agent/runs/delegated-tool",
            }
        if suffix == "/bundle":
            return {
                "ok": True,
                "run_id": run_id,
                "run_dir": "/agent/runs/delegated-tool",
                "bundle": {
                    "analysis_bundle": {"job_id": run_id},
                    "observation": {
                        "artifacts": [{"path": "artifacts/step-01-s1/result.json"}]
                    },
                },
                "warnings": ["proxied"],
            }
        raise AssertionError(f"unexpected suffix: {suffix}")

    monkeypatch.setattr(srv, "_proxy_agent_run_payload", _fake_proxy)
    monkeypatch.setattr(
        srv,
        "_load_bundle_and_scorecard",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("delegated bundle should not use local builder")
        ),
    )

    run = srv.run_get(run_id)
    assert run["ok"] is True
    assert run["run"]["status"] == "succeeded"
    assert run["run_dir"] == str(local_run_dir)
    persisted = json.loads((local_run_dir / "run.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "succeeded"
    assert persisted["finished_at"] == "2026-03-15T01:00:02Z"
    assert persisted["steps"][0]["status"] == "succeeded"
    assert persisted["steps"][0]["finished_at"] == "2026-03-15T01:00:02Z"

    bundle = srv.run_bundle_get(run_id)
    assert bundle["ok"] is True
    assert bundle["bundle"]["analysis_bundle"]["job_id"] == run_id
    assert bundle["bundle"]["observation"]["artifacts"]
    assert bundle["warnings"] == ["proxied"]


def test_pipeline_execute_delegates_single_step_run_facade(monkeypatch, tmp_path):
    from brain_researcher.services.mcp import server as srv

    _configure_agent_delegation_env(monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    def _fake_delegate(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "run_id": kwargs["run_id"],
            "status": "queued",
            "run_dir": "/agent/runs/delegated-plan",
        }

    monkeypatch.setattr(srv, "_delegate_execution_to_agent", _fake_delegate)

    work_dir = tmp_path / "work"
    out_dir = tmp_path / "out"
    resp = srv.pipeline_execute(
        {
            "steps": [
                {
                    "tool": "extract_timeseries",
                    "params": {"img": "x", "atlas": "y"},
                    "work_dir": str(work_dir),
                    "output_dir": str(out_dir),
                }
            ],
            "execution": {
                "schema_version": "br-plan-execution-v1",
                "allowed_tools": ["extract_timeseries"],
                "approval_level": "confirm",
                "run_mode_hint": "confirm_before_execute",
            },
        },
        dry_run=False,
        approval_phrase=srv.PIPELINE_EXECUTE_CONFIRM_PHRASE,
    )

    assert resp["ok"] is True
    assert resp["execution_mode"] == "agent_delegated"
    run_id = resp["run_id"]
    assert captured == {
        "run_id": run_id,
        "execution_type": "tool",
        "tool_id": "extract_timeseries",
        "params": {"img": "x", "atlas": "y"},
        "work_dir": str(work_dir),
        "output_dir": str(out_dir),
        "origin": "mcp_pipeline_execute",
    }

    local_run_dir = tmp_path / "runs" / run_id
    provenance = json.loads(
        (local_run_dir / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["delegated_execution"]["backend"] == "agent"
    assert provenance["delegated_execution"]["execution_type"] == "tool"

    def _fake_proxy(
        run_id_arg: str, *, suffix: str = "", method: str = "GET", payload=None
    ):
        assert run_id_arg == run_id
        assert method == "GET"
        assert payload is None
        if suffix == "":
            return {
                "ok": True,
                "run_id": run_id,
                "status": "completed",
                "progress": 1.0,
                "started_at": "2026-03-15T02:00:00Z",
                "finished_at": "2026-03-15T02:00:02Z",
                "run_dir": "/agent/runs/delegated-plan",
            }
        if suffix == "/scorecard?profile_id=external_coding_v1":
            return {
                "ok": True,
                "run_id": run_id,
                "run_dir": "/agent/runs/delegated-plan",
                "profile_id": "external_coding_v1",
                "scorecard": {
                    "completion_state": "succeeded",
                    "artifacts": {"completeness_ratio": 1.0},
                    "timing": {"steps_total": 1},
                },
                "warnings": ["proxied"],
            }
        raise AssertionError(f"unexpected suffix: {suffix}")

    monkeypatch.setattr(srv, "_proxy_agent_run_payload", _fake_proxy)
    monkeypatch.setattr(
        srv,
        "_load_bundle_and_scorecard",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("delegated scorecard should not use local builder")
        ),
    )

    listed = srv.run_list(limit=10)
    listed_run = next(item for item in listed["runs"] if item["run_id"] == run_id)
    assert listed_run["status"] == "succeeded"

    persisted = json.loads((local_run_dir / "run.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "succeeded"
    assert persisted["finished_at"] == "2026-03-15T02:00:02Z"
    assert persisted["steps"][0]["status"] == "succeeded"

    scorecard = srv.run_scorecard(run_id)
    assert scorecard["ok"] is True
    assert scorecard["scorecard"]["completion_state"] == "succeeded"
    assert scorecard["scorecard"]["artifacts"]["completeness_ratio"] == 1.0
    assert scorecard["warnings"] == ["proxied"]
