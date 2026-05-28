"""Regression tests for runtime_kind defaults and catalog model round-trips."""

from brain_researcher.services.agent.planner.catalog_loader import (
    PythonRunnerSpec,
    ResourceSpec,
    ToolCapability,
)
from brain_researcher.services.shared.planner.models import StepSpec


def test_stepspec_defaults_to_container_runtime():
    """Existing plans without runtime_kind should keep working."""
    step = StepSpec(id="step1", tool="fsl_bet")
    assert step.runtime_kind == "container"


def test_tool_capability_roundtrip_serialization():
    """ToolCapability with python runner survives JSON dump/load."""
    cap = ToolCapability(
        id="python.test.run",
        name="Python Test Tool",
        package="python",
        runtime_kind="python",
        modality=["fmri"],
        capabilities=["debug"],
        consumes=["timeseries"],
        produces=["connectivity_matrix"],
        resources=ResourceSpec(
            cpu_min=1,
            mem_mb_min=256,
            gpu=False,
            time_min_default=1.0,
        ),
        python=PythonRunnerSpec(
            module="brain_researcher.services.tools.demo_passthrough",
            function="run",
        ),
    )

    dumped = cap.model_dump_json()
    restored = ToolCapability.model_validate_json(dumped)

    assert restored == cap
    assert restored.python is not None
    assert restored.python.module == cap.python.module
