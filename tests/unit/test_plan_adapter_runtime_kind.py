"""Tests that runtime_kind survives plan_to_workflow() conversion."""
from __future__ import annotations

import pytest

from brain_researcher.services.orchestrator.plan_adapter import plan_to_workflow


def _minimal_plan(runtime_kind: str = "container") -> dict:
    """Return a minimal plan_payload with one step."""
    return {
        "plan_id": "test-plan-001",
        "version": 1,
        "context": {},
        "dag": {
            "steps": [
                {
                    "id": "step-bet",
                    "tool": "fsl_bet",
                    "runtime_kind": runtime_kind,
                    "params": {"input_file": "/data/T1w.nii.gz", "output_file": "/out/brain.nii.gz"},
                    "consumes": {},
                    "produces": {"brain_mask": "file"},
                }
            ],
            "artifacts": [],
        },
    }


class TestPlanAdapterRuntimeKind:
    def test_neurodesk_runtime_kind_preserved(self):
        plan = _minimal_plan("neurodesk")
        workflow = plan_to_workflow(plan)
        step = workflow.steps[0]
        assert step.metadata.get("runtime_kind") == "neurodesk"

    def test_container_runtime_kind_preserved(self):
        plan = _minimal_plan("container")
        workflow = plan_to_workflow(plan)
        step = workflow.steps[0]
        assert step.metadata.get("runtime_kind") == "container"

    def test_python_runtime_kind_preserved(self):
        plan = _minimal_plan("python")
        workflow = plan_to_workflow(plan)
        step = workflow.steps[0]
        assert step.metadata.get("runtime_kind") == "python"

    def test_default_runtime_kind_is_container_when_missing(self):
        """Steps without runtime_kind default to 'container'."""
        plan = _minimal_plan("container")
        # Remove runtime_kind from the step
        plan["dag"]["steps"][0].pop("runtime_kind")
        workflow = plan_to_workflow(plan)
        step = workflow.steps[0]
        assert step.metadata.get("runtime_kind") == "container"

    def test_consumes_and_produces_still_present(self):
        """Existing metadata keys are not broken by the change."""
        plan = _minimal_plan("neurodesk")
        workflow = plan_to_workflow(plan)
        step = workflow.steps[0]
        assert "consumes" in step.metadata
        assert "produces" in step.metadata
        assert step.metadata["produces"] == {"brain_mask": "file"}

    def test_workflow_step_tool_name(self):
        plan = _minimal_plan("neurodesk")
        workflow = plan_to_workflow(plan)
        assert workflow.steps[0].tool_name == "fsl_bet"

    def test_workflow_step_parameters(self):
        plan = _minimal_plan("neurodesk")
        workflow = plan_to_workflow(plan)
        params = workflow.steps[0].parameters
        assert params["input_file"] == "/data/T1w.nii.gz"
