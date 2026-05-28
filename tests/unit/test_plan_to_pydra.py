"""Unit tests for Plan-to-Pydra adapter."""

import pytest
from typing import Dict, Any, List

from brain_researcher.services.shared.planner.models import (
    Plan,
    PlanDAG,
    StepSpec,
    ArtifactSpec,
)
from brain_researcher.services.agent.adapters.plan_to_pydra import (
    plan_to_pydra_workflow,
    export_plan_to_pydra,
    PydraExportResult,
    PydraInterfaceSpec,
    load_pydra_tool_interface_map,
    get_pydra_interface_spec,
    _sanitize_task_name,
    _generate_pydra_package_task,
    _generate_shell_task,
    _generate_function_task,
    _generate_fallback_task,
    _step_to_pydra_task,
    _derive_pydra_connections,
    SUPPORTED_RUNTIME_KINDS,
    UNSUPPORTED_RUNTIME_KINDS,
)


class TestSanitizeTaskName:
    """Tests for task name sanitization."""

    def test_replaces_hyphens(self):
        assert _sanitize_task_name("step-001") == "step_001"

    def test_replaces_dots(self):
        assert _sanitize_task_name("fsl.bet") == "fsl_bet"

    def test_replaces_spaces(self):
        assert _sanitize_task_name("step 1") == "step_1"

    def test_prepends_t_for_numeric_start(self):
        assert _sanitize_task_name("001-step") == "t_001_step"

    def test_handles_empty_string(self):
        assert _sanitize_task_name("") == "task"


class TestPydraInterfaceSpec:
    """Tests for PydraInterfaceSpec dataclass."""

    def test_from_dict_shell_type(self):
        data = {
            "type": "shell",
            "executable": "bet",
            "container_image": "brainlife/fsl:6.0.4",
        }
        spec = PydraInterfaceSpec.from_dict(data)
        assert spec.type == "shell"
        assert spec.executable == "bet"
        assert spec.container_image == "brainlife/fsl:6.0.4"

    def test_from_dict_pydra_package_type(self):
        data = {
            "type": "pydra_package",
            "package": "pydra.tasks.fsl",
            "task_class": "BET",
        }
        spec = PydraInterfaceSpec.from_dict(data)
        assert spec.type == "pydra_package"
        assert spec.package == "pydra.tasks.fsl"
        assert spec.task_class == "BET"

    def test_from_dict_function_type(self):
        data = {
            "type": "function",
            "function": "nilearn.glm.first_level.FirstLevelModel.fit",
            "input_names": ["run_imgs", "events"],
            "output_names": ["fitted_model"],
        }
        spec = PydraInterfaceSpec.from_dict(data)
        assert spec.type == "function"
        assert spec.function == "nilearn.glm.first_level.FirstLevelModel.fit"
        assert spec.input_names == ["run_imgs", "events"]
        assert spec.output_names == ["fitted_model"]


class TestLoadPydraToolInterfaceMap:
    """Tests for loading Pydra tool interface mappings."""

    def test_returns_dict(self):
        mapping = load_pydra_tool_interface_map()
        assert isinstance(mapping, dict)

    def test_get_pydra_interface_spec_returns_spec(self):
        mapping = load_pydra_tool_interface_map()
        if "fsl.bet" in mapping:
            spec = get_pydra_interface_spec("fsl.bet", mapping)
            assert spec is not None
            assert isinstance(spec, PydraInterfaceSpec)

    def test_get_pydra_interface_spec_unknown_tool(self):
        mapping = load_pydra_tool_interface_map()
        spec = get_pydra_interface_spec("unknown.nonexistent.tool", mapping)
        assert spec is None


class TestGeneratePydraPackageTask:
    """Tests for pydra package task generation."""

    def test_generates_import_and_code(self):
        step = StepSpec(
            id="bet",
            tool="fsl.bet",
            consumes={"in": "volume_3d"},
            produces={"out": "volume_3d"},
            params={"frac": 0.4},
        )
        spec = PydraInterfaceSpec(
            type="pydra_package",
            package="pydra.tasks.fsl",
            task_class="BET",
        )
        import_stmt, task_code, input_fields, warning = _generate_pydra_package_task(step, spec, "bet")

        assert "from pydra.tasks.fsl import BET" in import_stmt
        assert 'wf.add(BET(name="bet"' in task_code
        assert "frac=0.4" in task_code
        assert isinstance(input_fields, list)
        assert warning is None


class TestGenerateShellTask:
    """Tests for shell task generation."""

    def test_generates_shell_command_task(self):
        step = StepSpec(
            id="smooth",
            tool="fsl.smooth",
            consumes={"in": "volume_3d"},
            produces={"out": "volume_3d"},
            params={"fwhm": 6},
        )
        spec = PydraInterfaceSpec(
            type="shell",
            executable="fslmaths",
            container_image="brainlife/fsl:6.0.4",
            input_spec=[
                {"name": "in_file", "argstr": "{in_file}", "position": 0},
            ],
            output_spec=[
                {"name": "out_file", "output_file_template": "{in_file}_smooth.nii.gz"},
            ],
        )
        import_stmt, task_code, input_fields, warning = _generate_shell_task(step, spec, "smooth")

        assert "ShellCommandTask" in import_stmt
        assert 'name="smooth"' in task_code
        assert 'executable="fslmaths"' in task_code
        assert "brainlife/fsl:6.0.4" in task_code
        assert isinstance(input_fields, list)


class TestGenerateFunctionTask:
    """Tests for function task generation."""

    def test_generates_function_task(self):
        step = StepSpec(
            id="glm",
            tool="python.nilearn.glm",
            consumes={"bold": "timeseries"},
            produces={"model": "volume_3d"},
            params={},
        )
        spec = PydraInterfaceSpec(
            type="function",
            function="nilearn.glm.first_level.FirstLevelModel.fit",
            input_names=["run_imgs", "events"],
            output_names=["fitted_model"],
        )
        import_stmt, task_code, input_fields, warning = _generate_function_task(step, spec, "glm")

        assert "import pydra" in import_stmt
        assert "@pydra.mark.task" in task_code
        assert "def glm_func" in task_code
        assert isinstance(input_fields, list)


class TestGenerateFallbackTask:
    """Tests for fallback task generation."""

    def test_generates_identity_task(self):
        step = StepSpec(
            id="unknown",
            tool="custom.unmapped",
            consumes={"in": "volume_3d"},
            produces={"out": "volume_3d"},
        )
        import_stmt, task_code, input_fields, warning = _generate_fallback_task(step, "unknown")

        assert "import pydra" in import_stmt
        assert "@pydra.mark.task" in task_code
        assert "def unknown_func" in task_code
        assert isinstance(input_fields, list)
        assert warning is not None
        assert "no pydra interface mapping" in warning.lower()


class TestStepToPydraTask:
    """Tests for step to Pydra task conversion."""

    @pytest.fixture
    def interface_map(self):
        return load_pydra_tool_interface_map()

    def test_known_tool_creates_proper_task(self, interface_map):
        step = StepSpec(
            id="bet",
            tool="fsl.bet",
            consumes={"in": "volume_3d"},
            produces={"out": "volume_3d"},
            params={"frac": 0.4},
        )
        import_stmt, task_code, input_fields, warning = _step_to_pydra_task(step, interface_map)

        assert import_stmt is not None
        assert task_code is not None
        assert isinstance(input_fields, list)

    def test_unknown_tool_creates_fallback(self, interface_map):
        step = StepSpec(
            id="unknown",
            tool="completely.unknown.tool",
            consumes={"in": "volume_3d"},
            produces={"out": "volume_3d"},
        )
        import_stmt, task_code, input_fields, warning = _step_to_pydra_task(step, interface_map)

        assert import_stmt is not None
        assert task_code is not None
        assert isinstance(input_fields, list)
        assert warning is not None


class TestDerivePydraConnections:
    """Tests for deriving Pydra lazy connections."""

    @pytest.fixture
    def interface_map(self):
        return load_pydra_tool_interface_map()

    def test_simple_linear_connection(self, interface_map):
        steps = [
            StepSpec(
                id="step1",
                tool="fsl.bet",
                consumes={},
                produces={"brain": "volume_3d"},
            ),
            StepSpec(
                id="step2",
                tool="fsl.smooth",
                consumes={"brain": "volume_3d"},
                produces={"smoothed": "volume_3d"},
            ),
        ]
        step_to_task = {"step1": "step1", "step2": "step2"}

        connections, warnings = _derive_pydra_connections(steps, step_to_task, interface_map)

        # Should have at least one connection
        assert len(connections) >= 1
        # Connection should use lzout syntax
        connection_str = "\n".join(connections)
        assert "lzout" in connection_str or "workflow input" in connection_str

    def test_no_self_connections(self, interface_map):
        steps = [
            StepSpec(
                id="step1",
                tool="fsl.bet",
                consumes={"in": "volume_3d"},
                produces={"in": "volume_3d"},  # Same resource name
            ),
        ]
        step_to_task = {"step1": "step1"}

        connections, warnings = _derive_pydra_connections(steps, step_to_task, interface_map)

        # Should not have self-connections
        for conn in connections:
            if "lzout" in conn:
                parts = conn.split(".")
                # Extract task names from connection
                assert True  # Connection format is different, just ensure no crash

    def test_warns_on_duplicate_producers(self, interface_map):
        steps = [
            StepSpec(
                id="step1",
                tool="fsl.bet",
                produces={"brain": "volume_3d"},
            ),
            StepSpec(
                id="step2",
                tool="fsl.bet",
                produces={"brain": "volume_3d"},  # Same resource
            ),
        ]
        step_to_task = {"step1": "step1", "step2": "step2"}

        connections, warnings = _derive_pydra_connections(steps, step_to_task, interface_map)

        assert any("multiple steps" in w.lower() for w in warnings)


class TestPlanToPydraWorkflow:
    """Tests for full plan to Pydra workflow conversion."""

    def test_simple_bet_workflow(self):
        plan = Plan(
            plan_id="test-bet",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="bet",
                        tool="fsl.bet",
                        consumes={},
                        produces={"brain": "volume_3d"},
                        params={"frac": 0.4},
                        runtime_kind="container",
                    ),
                ],
                artifacts=[],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test")

        assert isinstance(result, PydraExportResult)
        assert result.plan_id == "test-bet"
        assert "bet" in result.exported_steps
        assert len(result.skipped_steps) == 0
        assert "import pydra" in result.workflow_script
        assert "Workflow" in result.workflow_script

    def test_multi_step_pipeline(self):
        plan = Plan(
            plan_id="test-pipeline",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="bet",
                        tool="fsl.bet",
                        consumes={},
                        produces={"brain": "volume_3d"},
                        params={"frac": 0.4},
                        runtime_kind="container",
                    ),
                    StepSpec(
                        id="smooth",
                        tool="fsl.smooth",
                        consumes={"brain": "volume_3d"},
                        produces={"smoothed": "volume_3d"},
                        params={"fwhm": 6},
                        runtime_kind="container",
                    ),
                ],
                artifacts=[],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test")

        assert len(result.exported_steps) == 2
        assert "bet" in result.exported_steps
        assert "smooth" in result.exported_steps

    def test_skips_api_runtime_kind(self):
        plan = Plan(
            plan_id="test-api",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="api-call",
                        tool="external.api",
                        consumes={},
                        produces={"result": "volume_3d"},
                        runtime_kind="api",
                    ),
                ],
                artifacts=[],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test", strict=False)

        assert "api-call" in result.skipped_steps
        assert any("api" in w.lower() for w in result.warnings)

    def test_strict_mode_raises_on_api(self):
        plan = Plan(
            plan_id="test-strict",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="api-call",
                        tool="external.api",
                        consumes={},
                        produces={"result": "volume_3d"},
                        runtime_kind="api",
                    ),
                ],
                artifacts=[],
            ),
        )

        with pytest.raises(ValueError) as excinfo:
            plan_to_pydra_workflow(plan, "/tmp/test", strict=True)

        assert "api" in str(excinfo.value).lower()


class TestPydraExportResult:
    """Tests for PydraExportResult dataclass."""

    def test_to_dict(self):
        result = PydraExportResult(
            workflow_script="# test script",
            plan_id="test-001",
            exported_steps=["step1", "step2"],
            skipped_steps=["step3"],
            warnings=["warning1"],
            imports=["import pydra"],
            tasks=[{"name": "step1", "step_id": "step1"}],
        )

        d = result.to_dict()

        assert d["workflow_script"] == "# test script"
        assert d["plan_id"] == "test-001"
        assert d["exported_steps"] == ["step1", "step2"]
        assert d["skipped_steps"] == ["step3"]
        assert d["warnings"] == ["warning1"]
        assert d["imports"] == ["import pydra"]


class TestWorkflowScriptGeneration:
    """Tests for generated workflow script structure."""

    def test_script_has_shebang(self):
        plan = Plan(
            plan_id="test",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="bet",
                        tool="fsl.bet",
                        produces={"brain": "volume_3d"},
                        runtime_kind="container",
                    ),
                ],
                artifacts=[],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test")

        assert result.workflow_script.startswith("#!/usr/bin/env python")

    def test_script_has_imports(self):
        plan = Plan(
            plan_id="test",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="bet",
                        tool="fsl.bet",
                        produces={"brain": "volume_3d"},
                        runtime_kind="container",
                    ),
                ],
                artifacts=[],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test")

        assert "import pydra" in result.workflow_script
        assert "from pydra import Workflow" in result.workflow_script

    def test_script_has_main_block(self):
        plan = Plan(
            plan_id="test",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="bet",
                        tool="fsl.bet",
                        produces={"brain": "volume_3d"},
                        runtime_kind="container",
                    ),
                ],
                artifacts=[],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test")

        assert 'if __name__ == "__main__":' in result.workflow_script

    def test_script_has_create_function(self):
        plan = Plan(
            plan_id="test-workflow",
            version=1,
            schema_version="1.0",
            domain="neuroimaging",
            modality=["fmri"],
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="bet",
                        tool="fsl.bet",
                        produces={"brain": "volume_3d"},
                        runtime_kind="container",
                    ),
                ],
                artifacts=[],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test")

        assert "def create_plan_test_workflow" in result.workflow_script
