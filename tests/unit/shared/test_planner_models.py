"""Unit tests for shared planner contract models."""

import pytest
from pydantic import ValidationError

from brain_researcher.services.shared.planner.models import (
    ArtifactSpec,
    ConstraintSpec,
    Plan,
    PlanDAG,
    PlanRequest,
    RunPlanRequest,
    StepSpec,
)


def test_plan_roundtrip_serialization():
    steps = [
        StepSpec(id="s1", tool="fetch_atlas", consumes={}, produces={}),
    ]
    artifacts = [ArtifactSpec(name="atlas_path", rtype="parcellation_labels")]
    plan = Plan(
        plan_id="plan_test",
        domain="neuroimaging",
        modality=["fmri"],
        dag=PlanDAG(steps=steps, artifacts=artifacts),
        constraints=ConstraintSpec(tool_allowlist=["fetch_atlas"], max_steps=1),
    )

    payload = plan.model_dump(mode="json")
    restored = Plan.model_validate(payload)

    assert restored.plan_id == "plan_test"
    assert restored.dag.steps[0].tool == "fetch_atlas"
    assert restored.constraints.tool_allowlist == ["fetch_atlas"]


def test_plan_request_defaults():
    request = PlanRequest(
        pipeline="connectivity",
        domain="neuroimaging",
        modality=["fmri"],
        inputs={"fmri_img": "bold.nii.gz"},
        constraints=None,
    )

    assert request.pipeline == "connectivity"
    assert request.inputs["fmri_img"] == "bold.nii.gz"


def test_run_plan_request_validation():
    run_request = RunPlanRequest(plan_id="plan_123", version=1, por_token="stub")
    assert run_request.plan_id == "plan_123"


def test_plan_request_rejects_legacy_mode():
    with pytest.raises(ValidationError):
        PlanRequest(
            pipeline="connectivity",
            domain="neuroimaging",
            modality=["fmri"],
            mode="legacy",
        )
