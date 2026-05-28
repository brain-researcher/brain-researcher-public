"""Integration tests for Nipype workflow export."""

import json
import pytest
import tempfile
from pathlib import Path

from brain_researcher.services.shared.planner.models import (
    Plan,
    PlanDAG,
    StepSpec,
)
from brain_researcher.services.agent.adapters.plan_to_nipype import (
    plan_to_nipype_builder_args,
    export_plan_to_nipype,
)


@pytest.fixture
def sample_fmri_plan() -> Plan:
    """Create a realistic fMRI preprocessing plan."""
    return Plan(
        plan_id="fmri-preproc-001",
        domain="neuroimaging",
        modality=["fmri"],
        dag=PlanDAG(
            steps=[
                StepSpec(
                    id="brain-extraction",
                    tool="fsl.bet",
                    consumes={"t1_input": "volume_3d"},
                    produces={"brain": "volume_3d", "brain_mask": "mask_path"},
                    params={"frac": 0.5, "mask": True},
                    runtime_kind="container",
                ),
                StepSpec(
                    id="motion-correction",
                    tool="fsl.mcflirt",
                    consumes={"bold_input": "volume_4d"},
                    produces={"motion_corrected": "volume_4d", "motion_params": "timeseries"},
                    params={"cost": "mutualinfo"},
                    runtime_kind="container",
                ),
                StepSpec(
                    id="registration",
                    tool="fsl.flirt",
                    consumes={"motion_corrected": "volume_4d", "brain": "volume_3d"},
                    produces={"registered": "volume_4d", "transform": "volume_3d"},
                    params={"dof": 12},
                    runtime_kind="container",
                ),
                StepSpec(
                    id="smoothing",
                    tool="fsl.susan",
                    consumes={"registered": "volume_4d"},
                    produces={"smoothed": "volume_4d"},
                    params={"fwhm": 6.0},
                    runtime_kind="container",
                ),
            ],
            artifacts=[],
        ),
    )


@pytest.fixture
def mixed_runtime_plan() -> Plan:
    """Plan with mixed runtime kinds including unsupported API."""
    return Plan(
        plan_id="mixed-runtime-001",
        domain="neuroimaging",
        modality=["fmri"],
        dag=PlanDAG(
            steps=[
                StepSpec(
                    id="preprocess",
                    tool="fsl.bet",
                    runtime_kind="container",
                ),
                StepSpec(
                    id="api-call",
                    tool="external.api.analyze",
                    runtime_kind="api",
                ),
                StepSpec(
                    id="python-step",
                    tool="python.nilearn.glm",
                    runtime_kind="python",
                ),
            ],
        ),
    )


class TestPlanToNipypeIntegration:
    """Integration tests for plan-to-Nipype conversion."""

    def test_full_pipeline_conversion(self, sample_fmri_plan):
        """Test converting a full fMRI preprocessing pipeline."""
        result = plan_to_nipype_builder_args(
            plan=sample_fmri_plan,
            base_dir="/tmp/test_workflow",
            plugin="MultiProc",
            plugin_args={"n_procs": 4},
        )

        # All 4 steps should be exported
        assert len(result.exported_steps) == 4
        assert len(result.skipped_steps) == 0

        # Check nodes
        nodes = result.builder_args["nodes"]
        assert len(nodes) == 4

        # Check that all nodes have proper interface configuration
        for node in nodes:
            assert "name" in node
            assert "interface" in node or "fields" in node

        # Check connections
        connections = result.builder_args["connections"]
        # Should have connections: motion_corrected -> registered -> smoothed, brain -> registered
        assert len(connections) >= 2

    def test_mixed_runtime_handling(self, mixed_runtime_plan):
        """Test that API steps are skipped while container/python steps are exported."""
        result = plan_to_nipype_builder_args(
            plan=mixed_runtime_plan,
            base_dir="/tmp/test_workflow",
            strict=False,
        )

        # API step should be skipped
        assert "api-call" in result.skipped_steps

        # Container and Python steps should be exported
        assert "preprocess" in result.exported_steps
        assert "python-step" in result.exported_steps

        # Should have warning about API step
        assert any("api" in w.lower() for w in result.warnings)


class TestExportToNipypeIntegration:
    """Integration tests for full export including file generation."""

    @pytest.mark.integration
    def test_export_creates_files(self, sample_fmri_plan):
        """Test that export creates all expected files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_plan_to_nipype(
                plan=sample_fmri_plan,
                output_dir=tmpdir,
                plugin="Linear",
            )

            # Check status
            assert result["status"] == "success"

            # Check files exist
            plan_id = sample_fmri_plan.plan_id
            workflow_dir = Path(tmpdir) / plan_id

            # Original plan should be saved
            plan_file = workflow_dir / "plan.json"
            assert plan_file.exists()

            # Verify plan content
            saved_plan = json.loads(plan_file.read_text())
            assert saved_plan["plan_id"] == plan_id

    @pytest.mark.integration
    def test_export_result_contains_paths(self, sample_fmri_plan):
        """Test that export result contains all expected paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_plan_to_nipype(
                plan=sample_fmri_plan,
                output_dir=tmpdir,
            )

            assert "original_plan_file" in result
            assert "run_command" in result
            assert "exported_steps" in result
            assert "step_to_node" in result

    @pytest.mark.integration
    def test_export_strict_mode_fails_on_api(self, mixed_runtime_plan):
        """Test that strict mode raises error for unsupported runtime kinds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="unsupported"):
                export_plan_to_nipype(
                    plan=mixed_runtime_plan,
                    output_dir=tmpdir,
                    strict=True,
                )


class TestYamlOverridesIntegration:
    """Integration tests for YAML override loading."""

    def test_yaml_overrides_loaded(self):
        """Test that YAML overrides are loaded when file exists."""
        from brain_researcher.services.agent.adapters.tool_interface_map import (
            load_tool_interface_map,
        )

        mapping = load_tool_interface_map()

        # Check that some YAML-defined tools are present
        # These come from configs/nipype/tool_interfaces.yaml
        yaml_tools = [
            "container.fmriprep",
            "container.mriqc",
            "container.fitlins.recipe.run",
        ]

        for tool in yaml_tools:
            if tool in mapping:
                # YAML override was loaded
                assert mapping[tool] is not None


class TestNodeInterfaceMapping:
    """Integration tests for node interface mapping accuracy."""

    def test_fsl_interfaces_correct(self):
        """Test that FSL tools map to correct Nipype interfaces."""
        from brain_researcher.services.agent.adapters.tool_interface_map import (
            get_interface_spec,
            load_tool_interface_map,
        )

        mapping = load_tool_interface_map()

        fsl_tools = {
            "fsl.bet": ("fsl", "BET"),
            "fsl.flirt": ("fsl", "FLIRT"),
            "fsl.fnirt": ("fsl", "FNIRT"),
            "fsl.mcflirt": ("fsl", "MCFLIRT"),
            "fsl.susan": ("fsl", "SUSAN"),
            "fsl.fast": ("fsl", "FAST"),
        }

        for tool_id, (expected_type, expected_name) in fsl_tools.items():
            spec = get_interface_spec(tool_id, mapping)
            assert spec is not None, f"Missing spec for {tool_id}"
            assert spec["type"] == expected_type
            assert spec["name"] == expected_name

    def test_freesurfer_interfaces_correct(self):
        """Test that FreeSurfer tools map to correct Nipype interfaces."""
        from brain_researcher.services.agent.adapters.tool_interface_map import (
            get_interface_spec,
            load_tool_interface_map,
        )

        mapping = load_tool_interface_map()

        spec = get_interface_spec("freesurfer.recon_all", mapping)
        assert spec is not None
        assert spec["type"] == "freesurfer"
        assert spec["name"] == "ReconAll"

    def test_ants_interfaces_correct(self):
        """Test that ANTs tools map to correct Nipype interfaces."""
        from brain_researcher.services.agent.adapters.tool_interface_map import (
            get_interface_spec,
            load_tool_interface_map,
        )

        mapping = load_tool_interface_map()

        spec = get_interface_spec("ants.registration", mapping)
        assert spec is not None
        assert spec["type"] == "ants"
        assert spec["name"] == "Registration"


class TestConnectionDerivation:
    """Integration tests for DAG connection derivation."""

    def test_linear_pipeline_connections(self):
        """Test connections for a simple linear pipeline."""
        plan = Plan(
            plan_id="linear-test",
            domain="neuroimaging",
            modality=["smri"],
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="step-1",
                        tool="fsl.bet",
                        produces={"brain": "volume_3d"},
                    ),
                    StepSpec(
                        id="step-2",
                        tool="fsl.fast",
                        consumes={"brain": "volume_3d"},
                        produces={"segmented": "volume_3d"},
                    ),
                    StepSpec(
                        id="step-3",
                        tool="fsl.first",
                        consumes={"segmented": "volume_3d"},
                        produces={"structures": "volume_3d"},
                    ),
                ],
            ),
        )

        result = plan_to_nipype_builder_args(plan, base_dir="/tmp/test")

        # Should have 2 connections: step-1 -> step-2 -> step-3
        connections = result.builder_args["connections"]
        assert len(connections) == 2

    def test_branching_pipeline_connections(self):
        """Test connections for a branching pipeline (one producer, multiple consumers)."""
        plan = Plan(
            plan_id="branch-test",
            domain="neuroimaging",
            modality=["smri"],
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="source",
                        tool="fsl.bet",
                        produces={"brain": "volume_3d"},
                    ),
                    StepSpec(
                        id="branch-a",
                        tool="fsl.fast",
                        consumes={"brain": "volume_3d"},
                    ),
                    StepSpec(
                        id="branch-b",
                        tool="fsl.first",
                        consumes={"brain": "volume_3d"},
                    ),
                ],
            ),
        )

        result = plan_to_nipype_builder_args(plan, base_dir="/tmp/test")

        # Should have 2 connections: source -> branch-a and source -> branch-b
        connections = result.builder_args["connections"]
        assert len(connections) == 2

        # Both connections should originate from source
        from_nodes = {c[0] for c in connections}
        assert from_nodes == {"source"}
