"""Integration-style tests for ChatOrchestrator pipeline branch.

These tests validate that when `use_planning_engine` is requested, the
orchestrator will:
1) Call the (mocked) PlanningEngine to obtain a plan with WorkflowStep items.
2) Execute each step via the (mocked) execute_tool helper.
3) Summarize via the router (also mocked) and return a pipeline reply with
   metadata and tool_calls containing the planned steps.

We purposely mock external dependencies (LLM, tool execution, planner) to keep
the test fast and deterministic.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator
from brain_researcher.services.agent.planning import WorkflowStep, QueryIntent


class DummyMemory:
    def append(self, *args, **kwargs):
        return None

    def render_recent(self, thread_id: str, limit: int = 4):
        return ""


class DummyRouter:
    def route_chat(self, *args, **kwargs):
        return SimpleNamespace(text="pipeline summary", metadata=None)


class DummyPlanner:
    """Returns a fixed two-step plan for testing."""

    def __init__(self, *args, **kwargs):
        pass

    def _should_use_pipeline(self, intent, query):
        return True

    async def _generate_steps(self, query, intent, context=None):
        return self._steps()

    async def generate_plan(self, query, intent=None, context=None):
        return SimpleNamespace(steps=self._steps())

    def _steps(self):
        return [
            WorkflowStep(
                step_id="s1",
                step_number=1,
                description="Skull strip",
                tool_name="fsl.bet",
                tool_args={"input_file": "/tmp/sub-01_T1w.nii.gz"},
            ),
            WorkflowStep(
                step_id="s2",
                step_number=2,
                description="Register to MNI",
                tool_name="fsl.fnirt",
                tool_args={"in_file": "/tmp/sub-01_T1w_brain.nii.gz"},
                dependencies=["s1"],
            ),
        ]


def test_pipeline_branch_returns_pipeline_reply(monkeypatch):
    """ChatOrchestrator should return a pipeline reply when planning succeeds."""

    # Patch PlanningEngine used inside orchestrator to our deterministic planner
    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.PlanningEngine",
        DummyPlanner,
    )

    # Patch execute_tool to avoid running real tools
    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(tool_id, params, **kwargs):
        return ToolResult(status="success", data={"tool_id": tool_id, "params": params})

    monkeypatch.setattr(
        "brain_researcher.services.tools.executor.execute_tool",
        fake_execute_tool,
    )

    orch = ChatOrchestrator(
        router=DummyRouter(),
        tool_executor=None,
        tool_registry=None,
        tool_router=None,
        memory=DummyMemory(),
        error_recovery=None,
    )

    reply = orch.handle_chat(
        "preprocess my T1 to MNI space",
        history=[],
        ctx={"use_planning_engine": True, "pipeline_preview": True},
    )

    assert reply.metadata.get("type") == "pipeline"
    assert reply.metadata.get("mode") == "preview"
    assert reply.tool_calls, "expected pipeline tool_calls"

    pipeline_steps = reply.tool_calls[0].get("pipeline_steps", [])
    step_tools = {s.get("tool_name") or s.get("tool") or s.get("tool_id") for s in pipeline_steps}
    assert {"fsl.bet", "fsl.fnirt"}.issubset(step_tools)

    # Ensure the mocked execute_tool data was preserved
    bet = pipeline_steps[0]
    assert bet.get("tool_args", {}).get("input_file") == "/tmp/sub-01_T1w.nii.gz"


def test_pipeline_ds000030_preview(monkeypatch):
    """Golden-path preview for ds000030 T1 → BET → FNIRT."""

    data_root = "/app/data/openneuro/ds000030"
    bids_t1 = f"{data_root}/sub-01/anat/sub-01_T1w.nii.gz"
    brain_out = f"{data_root}/derivatives/sub-01_T1w_brain.nii.gz"

    steps = [
        WorkflowStep(
            step_id="s1",
            step_number=1,
            description="Skull strip ds000030",
            tool_name="fsl.bet",
            tool_args={"input_file": bids_t1, "out_file": brain_out, "frac": 0.5},
        ),
        WorkflowStep(
            step_id="s2",
            step_number=2,
            description="Register brain to MNI",
            tool_name="fsl.fnirt",
            tool_args={"in_file": brain_out, "ref_file": "MNI152"},
            dependencies=["s1"],
        ),
    ]

    class DSPlanner(DummyPlanner):
        def _steps(self):
            return steps

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.PlanningEngine",
        DSPlanner,
    )

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(tool_id, params, **kwargs):
        # echo back the params for assertion
        return ToolResult(status="success", data={"tool_id": tool_id, "params": params})

    monkeypatch.setattr(
        "brain_researcher.services.tools.executor.execute_tool",
        fake_execute_tool,
    )

    orch = ChatOrchestrator(
        router=DummyRouter(),
        tool_executor=None,
        tool_registry=None,
        tool_router=None,
        memory=DummyMemory(),
        error_recovery=None,
    )

    reply = orch.handle_chat(
        "Run ds000030 T1 preprocessing to MNI",
        history=[],
        ctx={
            "use_planning_engine": True,
            "pipeline_preview": True,
            "dataset_id": "ds000030",
        },
    )

    assert reply.metadata.get("type") == "pipeline"
    assert reply.metadata.get("mode") == "preview"
    pipeline_steps = reply.tool_calls[0].get("pipeline_steps", [])
    step_tools = {s.get("tool_name") or s.get("tool") or s.get("tool_id") for s in pipeline_steps}
    assert {"fsl.bet", "fsl.fnirt"}.issubset(step_tools)

    # verify the real dataset path was carried through
    bet = pipeline_steps[0]
    assert bet.get("tool_args", {}).get("input_file") == bids_t1
    assert bet.get("tool_args", {}).get("out_file") == brain_out


def test_pipeline_ica_fix_clustsim_preview(monkeypatch):
    """ICA+FIX+ClustSim pipeline should flow through preview path."""

    func_path = "/app/data/openneuro/ds000030/sub-01/func/sub-01_task-rest_bold.nii.gz"
    mask_path = "/app/data/openneuro/ds000030/derivatives/sub-01_brain_mask.nii.gz"
    training = "/opt/fix/training.RData"

    steps = [
        WorkflowStep(
            step_id="s1",
            step_number=1,
            description="MELODIC ICA",
            tool_name="fsl.melodic",
            tool_args={
                "fmri_file": func_path,
                "tr": 2.0,
                "output_dir": "/tmp/out/melodic",
                "mask": mask_path,
            },
        ),
        WorkflowStep(
            step_id="s2",
            step_number=2,
            description="FIX classify",
            tool_name="fsl.fslFixText",
            tool_args={
                "melodic_dir": "/tmp/out/melodic",
                "training_file": training,
                "threshold": 20,
            },
            dependencies=["s1"],
        ),
        WorkflowStep(
            step_id="s3",
            step_number=3,
            description="ClustSim",
            tool_name="afni.3dClustSim",
            tool_args={
                "mask": mask_path,
                "voxel_pthr": 0.001,
                "iterations": 5000,
            },
            dependencies=["s2"],
        ),
    ]

    class ICAPlanner(DummyPlanner):
        def _steps(self):
            return steps

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.PlanningEngine",
        ICAPlanner,
    )

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(tool_id, params, **kwargs):
        return ToolResult(status="success", data={"tool_id": tool_id, "params": params})

    monkeypatch.setattr(
        "brain_researcher.services.tools.executor.execute_tool",
        fake_execute_tool,
    )

    orch = ChatOrchestrator(
        router=DummyRouter(),
        tool_executor=None,
        tool_registry=None,
        tool_router=None,
        memory=DummyMemory(),
        error_recovery=None,
    )

    reply = orch.handle_chat(
        "Run ICA + FIX denoising and cluster correction",
        history=[],
        ctx={"use_planning_engine": True, "pipeline_preview": True},
    )

    assert reply.metadata.get("type") == "pipeline"
    pipeline_steps = reply.tool_calls[0].get("pipeline_steps", [])
    tools = [s.get("tool_name") for s in pipeline_steps]
    assert tools == ["fsl.melodic", "fsl.fslFixText", "afni.3dClustSim"]

    # Ensure arguments propagated
    melodic = pipeline_steps[0]["tool_args"]
    assert melodic["fmri_file"] == func_path
    clust = pipeline_steps[-1]["tool_args"]
    assert clust["iterations"] == 5000
