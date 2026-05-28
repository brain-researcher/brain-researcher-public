"""Integration tests for Pydra workflow export."""

import json
import pytest
import tempfile
import importlib.util
from pathlib import Path

from brain_researcher.services.shared.planner.models import (
    Plan,
    PlanDAG,
    StepSpec,
)
from brain_researcher.services.agent.adapters.plan_to_pydra import (
    plan_to_pydra_workflow,
    export_plan_to_pydra,
    PydraExportResult,
)


@pytest.fixture
def sample_fmri_plan() -> Plan:
    """Create a realistic fMRI preprocessing plan."""
    return Plan(
        plan_id="fmri-preproc-pydra-001",
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
        plan_id="mixed-runtime-pydra-001",
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


@pytest.fixture
def simple_bet_plan() -> Plan:
    """Simple single-step BET plan for basic testing."""
    return Plan(
        plan_id="simple-bet-pydra",
        domain="neuroimaging",
        modality=["fmri"],
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


class TestPlanToPydraIntegration:
    """Integration tests for plan-to-Pydra conversion."""

    def test_full_pipeline_conversion(self, sample_fmri_plan):
        """Test converting a full fMRI preprocessing pipeline."""
        result = plan_to_pydra_workflow(
            plan=sample_fmri_plan,
            base_dir="/tmp/test",
        )

        assert isinstance(result, PydraExportResult)
        assert result.plan_id == "fmri-preproc-pydra-001"
        assert len(result.exported_steps) == 4
        assert len(result.skipped_steps) == 0

        # Verify workflow script is valid Python syntax
        compile(result.workflow_script, "<string>", "exec")

    def test_mixed_runtime_skips_api(self, mixed_runtime_plan):
        """Test that API runtime kind is skipped with warning."""
        result = plan_to_pydra_workflow(
            plan=mixed_runtime_plan,
            base_dir="/tmp/test",
            strict=False,
        )

        assert "api-call" in result.skipped_steps
        assert "preprocess" in result.exported_steps
        assert "python-step" in result.exported_steps
        assert any("api" in w.lower() for w in result.warnings)

    def test_strict_mode_fails_on_api(self, mixed_runtime_plan):
        """Test that strict mode raises error for API runtime."""
        with pytest.raises(ValueError) as excinfo:
            plan_to_pydra_workflow(
                plan=mixed_runtime_plan,
                base_dir="/tmp/test",
                strict=True,
            )

        assert "api" in str(excinfo.value).lower()


class TestExportPlanToPydra:
    """Integration tests for full export_plan_to_pydra function."""

    def test_export_creates_files(self, simple_bet_plan):
        """Test that export creates workflow files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_plan_to_pydra(
                plan=simple_bet_plan,
                output_dir=tmpdir,
                strict=False,
            )

            assert result["status"] == "success"
            assert result["format"] == "pydra"
            assert result["plan_id"] == "simple-bet-pydra"

            # Check files were created
            workflow_file = Path(result["workflow_file"])
            assert workflow_file.exists()
            assert workflow_file.suffix == ".py"

            plan_file = Path(result["original_plan_file"])
            assert plan_file.exists()

            spec_file = Path(result["spec_file"])
            assert spec_file.exists()

    def test_export_workflow_is_valid_python(self, simple_bet_plan):
        """Test that exported workflow.py is valid Python."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_plan_to_pydra(
                plan=simple_bet_plan,
                output_dir=tmpdir,
            )

            workflow_file = Path(result["workflow_file"])
            content = workflow_file.read_text()

            # Should compile without syntax errors
            compile(content, workflow_file.name, "exec")

    def test_export_saves_original_plan(self, simple_bet_plan):
        """Test that original plan is saved for provenance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_plan_to_pydra(
                plan=simple_bet_plan,
                output_dir=tmpdir,
            )

            plan_file = Path(result["original_plan_file"])
            saved_plan = json.loads(plan_file.read_text())

            assert saved_plan["plan_id"] == "simple-bet-pydra"
            assert "dag" in saved_plan
            assert len(saved_plan["dag"]["steps"]) == 1

    def test_export_creates_spec_yaml(self, simple_bet_plan):
        """Test that export creates spec.yaml with workflow metadata."""
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            result = export_plan_to_pydra(
                plan=simple_bet_plan,
                output_dir=tmpdir,
            )

            spec_file = Path(result["spec_file"])
            spec_data = yaml.safe_load(spec_file.read_text())

            assert "workflow_name" in spec_data
            assert "exported_steps" in spec_data
            assert "imports" in spec_data


class TestPydraWorkflowStructure:
    """Tests for the structure of generated Pydra workflows."""

    def test_workflow_has_imports(self, simple_bet_plan):
        """Test that workflow has required imports."""
        result = plan_to_pydra_workflow(simple_bet_plan, "/tmp/test")

        assert "import pydra" in result.workflow_script
        assert "from pydra import Workflow" in result.workflow_script

    def test_workflow_has_create_function(self, simple_bet_plan):
        """Test that workflow has a create function."""
        result = plan_to_pydra_workflow(simple_bet_plan, "/tmp/test")

        assert "def create_plan_simple_bet_pydra" in result.workflow_script

    def test_workflow_has_main_block(self, simple_bet_plan):
        """Test that workflow has if __name__ == '__main__' block."""
        result = plan_to_pydra_workflow(simple_bet_plan, "/tmp/test")

        assert 'if __name__ == "__main__":' in result.workflow_script

    def test_workflow_has_cache_dir(self, simple_bet_plan):
        """Test that workflow specifies cache_dir."""
        result = plan_to_pydra_workflow(simple_bet_plan, "/tmp/test_cache")

        assert "cache_dir=" in result.workflow_script
        assert "/tmp/test_cache" in result.workflow_script


class TestPydraConnectionDerivation:
    """Tests for Pydra connection derivation in multi-step workflows."""

    def test_linear_pipeline_connections(self, sample_fmri_plan):
        """Test connections in a linear pipeline."""
        result = plan_to_pydra_workflow(sample_fmri_plan, "/tmp/test")

        # Should have connection code for the pipeline
        # Look for lzout connections or workflow input comments
        has_connections = (
            "lzout" in result.workflow_script or
            "workflow input" in result.workflow_script
        )
        assert has_connections, "Workflow should have task connections"

    def test_branch_merge_connections(self):
        """Test connections in a branching pipeline."""
        plan = Plan(
            plan_id="branch-merge",
            domain="neuroimaging",
            modality=["fmri"],
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="input",
                        tool="fsl.bet",
                        produces={"brain": "volume_3d"},
                        runtime_kind="container",
                    ),
                    StepSpec(
                        id="branch1",
                        tool="fsl.smooth",
                        consumes={"brain": "volume_3d"},
                        produces={"smooth1": "volume_3d"},
                        runtime_kind="container",
                    ),
                    StepSpec(
                        id="branch2",
                        tool="fsl.flirt",
                        consumes={"brain": "volume_3d"},
                        produces={"registered": "volume_3d"},
                        runtime_kind="container",
                    ),
                ],
            ),
        )

        result = plan_to_pydra_workflow(plan, "/tmp/test")

        # All steps should be exported
        assert len(result.exported_steps) == 3


class TestPydraExportEndpoint:
    """Tests for the unified export endpoint (requires running service)."""

    @pytest.mark.skipif(
        True,  # Skip by default, enable for manual testing
        reason="Requires running agent service"
    )
    def test_unified_endpoint_pydra_format(self, simple_bet_plan):
        """Test the unified /agent/plan/export endpoint with pydra format."""
        import requests

        response = requests.post(
            "http://localhost:8000/agent/plan/export",
            json={
                "plan": simple_bet_plan.model_dump(),
                "format": "pydra",
                "options": {"strict": False},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "pydra"
        assert data["status"] == "success"
