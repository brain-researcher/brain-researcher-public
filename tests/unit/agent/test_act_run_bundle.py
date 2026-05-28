from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class DemoArgs(BaseModel):
    required_value: str = Field(..., description="Required string to satisfy schema")


class DemoTool:
    EXAMPLES = []

    def get_tool_name(self) -> str:
        return "mcp.test_schema_mismatch"

    def get_tool_description(self) -> str:
        return "(TEST) Deterministic tool used for /act closed-loop unit tests."

    def get_args_schema(self):
        return DemoArgs

    def run(self, **kwargs):
        return {"status": "success", "data": kwargs}


class DemoRegistry:
    def __init__(self, tool: DemoTool):
        self._tools = {tool.get_tool_name(): tool}

    def get_all_tools(self):
        return list(self._tools.values())

    def get_tool(self, name: str):
        return self._tools.get(name)

    def register_tool(self, tool):
        self._tools[tool.get_tool_name()] = tool


class DemoAgent:
    def __init__(self, tool_registry: DemoRegistry):
        self.tool_registry = tool_registry


def test_act_core_writes_run_bundle(monkeypatch, tmp_path):
    from brain_researcher.config.run_artifacts import reset_recorder_config

    monkeypatch.delenv("LLM_ONLY_FALLBACK", raising=False)
    monkeypatch.delenv("DISABLE_TOOL_DISCOVERY", raising=False)
    monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
    reset_recorder_config()

    tool = DemoTool()
    agent = DemoAgent(DemoRegistry(tool))

    import brain_researcher.services.agent.web_service as web_service

    monkeypatch.setattr(web_service, "get_agent", lambda: agent)

    from brain_researcher.services.agent.agent_core import agent_act_core

    payload = {
        "query": "Please run mcp.test_schema_mismatch",
        "session_id": "sess_test",
        "tool_mode": "force",
        "tools_whitelist": ["mcp.test_schema_mismatch"],
        "tool_params": {"required_value": "ok"},
        "budget_ms": 2000,
    }

    result = agent_act_core(
        payload, trace_id="trace_test", run_id="run_test_act_bundle"
    )

    assert "error" not in result
    assert result.get("runCard", {}).get("schema_version") == "run-card-v1"
    assert result["runCard"]["ids"]["job_id"] == "run_test_act_bundle"
    assert result["runCard"]["ids"]["run_id"] == "run_test_act_bundle"
    assert result["runCard"]["ids"]["trace_id"] == "trace_test"
    assert result["runCard"]["ids"]["session_id"] == "sess_test"
    assert "policy" in result["runCard"]
    assert "versions" in result["runCard"]
    assert result["tool_calls"]
    call = result["tool_calls"][0]
    assert call["status"] == "ok"
    assert call["tool_call_id"]

    run_dir = Path(result["runCard"]["provenance"]["run_dir"])
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "trajectory.json").exists()
    assert (run_dir / "observation.json").exists()
    assert (run_dir / "analysis_bundle.json").exists()
    assert (run_dir / "provenance.json").exists()

    trace_lines = (
        (run_dir / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    )
    assert trace_lines, "trace.jsonl should contain at least one event"
    from pydantic import TypeAdapter

    from brain_researcher.core.contracts.analysis_bundle import AnalysisBundleV1
    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisStreamEventTypeV1,
        AnalysisStreamEventV1,
    )
    from brain_researcher.core.contracts.observation import ObservationSpecV1

    adapter = TypeAdapter(AnalysisStreamEventV1)
    events = [adapter.validate_python(json.loads(line)) for line in trace_lines]
    assert all(e.ids.job_id == "run_test_act_bundle" for e in events)
    assert all(e.ids.run_id == "run_test_act_bundle" for e in events)

    event_types = {e.event_type for e in events}
    assert AnalysisStreamEventTypeV1.tool_call_started.value in event_types
    assert AnalysisStreamEventTypeV1.tool_call_finished.value in event_types

    obs = ObservationSpecV1.model_validate_json(
        (run_dir / "observation.json").read_text(encoding="utf-8")
    )
    assert obs.job_id == "run_test_act_bundle"

    bundle = AnalysisBundleV1.model_validate_json(
        (run_dir / "analysis_bundle.json").read_text(encoding="utf-8")
    )
    assert bundle.job_id == "run_test_act_bundle"
    assert bundle.files.execution_manifest_json == "execution_manifest.json"
    assert bundle.execution_manifest is not None
    assert bundle.files.user_docker_compose_yml == ".bundle_support/docker-compose.yml"
    assert bundle.files.user_environment_yml == ".bundle_support/environment.yml"
    assert bundle.files.user_env_example == ".bundle_support/.env.example"
    assert bundle.files.user_quickstart_md == ".bundle_support/quickstart.md"
    assert bundle.files.user_installation_md == ".bundle_support/installation.md"
    assert (run_dir / bundle.files.user_docker_compose_yml).exists()
    assert (run_dir / bundle.files.user_environment_yml).exists()

    tool_run_dir = Path(call["run_dir"])
    assert tool_run_dir.is_dir()
    assert str(tool_run_dir).startswith(str(run_dir))
    assert call["provenance_path"] == str(tool_run_dir / "provenance.json")
    assert (tool_run_dir / "provenance.json").exists()

    from brain_researcher.core.contracts.provenance import ProvenanceV1

    tool_prov = ProvenanceV1.model_validate_json(
        (tool_run_dir / "provenance.json").read_text(encoding="utf-8")
    )
    assert tool_prov.run_id == call["execution_id"]
    assert (tool_run_dir / "hash.json").exists()


def test_persist_agent_analysis_bundle_writes_native_review_context(tmp_path):
    from brain_researcher.services.agent.run_bundle import (
        persist_agent_analysis_bundle,
        persist_agent_observation,
    )

    run_dir = tmp_path / "run-direct"
    run_dir.mkdir()
    (run_dir / "provenance.json").write_text(
        json.dumps({"schema_version": "provenance-v1"}),
        encoding="utf-8",
    )
    (run_dir / "threshold_summary.json").write_text(
        json.dumps({"n_clusters_surviving": 1}),
        encoding="utf-8",
    )
    (run_dir / "correction_summary.json").write_text(
        json.dumps({"method": "fdr", "alpha": 0.05}),
        encoding="utf-8",
    )
    (run_dir / "design_matrix.csv").write_text(
        "intercept,task\n1,0\n1,1\n",
        encoding="utf-8",
    )
    (run_dir / "contrast_table.csv").write_text(
        "contrast_name,intercept,task\nmain_effect,0,1\n",
        encoding="utf-8",
    )
    (run_dir / "cluster_table.csv").write_text(
        "cluster_id,cluster_size,p_fwe\n1,42,0.01\n",
        encoding="utf-8",
    )
    (run_dir / "peak_table.csv").write_text(
        "x,y,z,peak_z,cluster_id\n12,-8,50,5.1,1\n",
        encoding="utf-8",
    )

    run_card = {
        "id": "run-direct",
        "parameters": {
            "target_column": "story_score",
            "split_unit": "subject",
            "grouped_split_keys": ["subject"],
            "required_group_keys": ["subject"],
            "best_model": "ridge",
            "model_candidates": ["ridge", "lasso"],
            "selection_accounting": "nested_cv",
        },
    }
    provenance = {
        "schema_version": "provenance-v1",
        "command": ["python", "analysis.py"],
        "environment": {"python_version": "3.11.9"},
        "parameters": {
            "correction_summary_path": "correction_summary.json",
            "threshold_summary_path": "threshold_summary.json",
            "design_matrix_path": "design_matrix.csv",
            "contrast_table_path": "contrast_table.csv",
            "cluster_table_path": "cluster_table.csv",
            "peak_table_path": "peak_table.csv",
        },
    }

    persist_agent_observation(
        run_dir,
        job_id="run-direct",
        run_id="run-direct",
        state="succeeded",
        run_card=run_card,
        provenance=provenance,
    )
    persist_agent_analysis_bundle(
        run_dir,
        job_id="run-direct",
        run_id="run-direct",
        state="succeeded",
        run_card=run_card,
        provenance=provenance,
    )

    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    assert (run_dir / "artifact_manifest.json").exists()
    assert bundle["files"]["artifact_manifest_json"] == "artifact_manifest.json"
    assert bundle["artifact_manifest"]["schema_version"] == "artifact-manifest-v1"
    assert bundle["review_context"]["selection"]["best_model"] == "ridge"
    assert bundle["review_context"]["selection"]["selection_accounting"] == "nested_cv"
    assert bundle["files"]["correction_summary_json"] == "correction_summary.json"
    assert bundle["files"]["threshold_summary_json"] == "threshold_summary.json"
    assert bundle["files"]["design_matrix"] == "design_matrix.csv"
    assert bundle["files"]["contrast_table"] == "contrast_table.csv"
    assert bundle["files"]["cluster_table"] == "cluster_table.csv"
    assert bundle["files"]["peak_table"] == "peak_table.csv"
    assert (
        bundle["observation"]["run_card"]["review_context"]["selection"]["best_model"]
        == "ridge"
    )


def test_agent_trace_events_are_typed(tmp_path):
    from pydantic import TypeAdapter

    from brain_researcher.core.contracts.analysis_stream import (
        AnalysisCompletedEventV1,
        AnalysisStreamEventV1,
        JobStartedEventV1,
        ToolCallFinishedEventV1,
        ToolCallStartedEventV1,
    )
    from brain_researcher.services.agent.run_bundle import log_trace_event

    run_dir = tmp_path / "run-agent-trace"
    for event_type, payload in (
        ("agent.run.started", {"job_id": "job_agent"}),
        (
            "agent.step.started",
            {"job_id": "job_agent", "step_id": "s1", "tool_id": "demo.tool"},
        ),
        (
            "agent.step.finished",
            {
                "job_id": "job_agent",
                "step_id": "s1",
                "tool_id": "demo.tool",
                "status": "succeeded",
            },
        ),
        ("agent.run.finished", {"job_id": "job_agent", "status": "succeeded"}),
    ):
        log_trace_event(
            run_dir, run_id="job_agent", event_type=event_type, payload=payload
        )

    adapter = TypeAdapter(AnalysisStreamEventV1)
    events = [
        adapter.validate_python(json.loads(line))
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert isinstance(events[0], JobStartedEventV1)
    assert isinstance(events[1], ToolCallStartedEventV1)
    assert isinstance(events[2], ToolCallFinishedEventV1)
    assert isinstance(events[3], AnalysisCompletedEventV1)
