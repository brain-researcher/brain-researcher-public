"""Unit tests for Plan-to-Nipype adapter."""

import pytest
from typing import Dict, Any, List

from brain_researcher.services.shared.planner.models import (
    Plan,
    PlanDAG,
    StepSpec,
    ArtifactSpec,
)
from brain_researcher.services.agent.adapters.plan_to_nipype import (
    plan_to_nipype_builder_args,
    NipypeExportResult,
    _sanitize_node_name,
    _map_step_to_node,
    _derive_connections,
    SUPPORTED_RUNTIME_KINDS,
    UNSUPPORTED_RUNTIME_KINDS,
)
from brain_researcher.services.agent.adapters.tool_interface_map import (
    load_tool_interface_map,
    get_interface_spec,
    CORE_TOOL_TO_INTERFACE,
)


class TestSanitizeNodeName:
    """Tests for node name sanitization."""

    def test_replaces_hyphens(self):
        assert _sanitize_node_name("step-001") == "step_001"

    def test_replaces_dots(self):
        assert _sanitize_node_name("fsl.bet") == "fsl_bet"

    def test_replaces_spaces(self):
        assert _sanitize_node_name("step 1") == "step_1"

    def test_prepends_n_for_numeric_start(self):
        assert _sanitize_node_name("001-step") == "n_001_step"

    def test_handles_empty_string(self):
        assert _sanitize_node_name("") == "node"


class TestToolInterfaceMap:
    """Tests for tool-to-interface mapping."""

    def test_core_mappings_exist(self):
        assert "fsl.bet" in CORE_TOOL_TO_INTERFACE
        assert "fsl.smooth" in CORE_TOOL_TO_INTERFACE
        assert "freesurfer.recon_all" in CORE_TOOL_TO_INTERFACE
        assert "ants.registration" in CORE_TOOL_TO_INTERFACE

    def test_get_interface_spec_exact_match(self):
        spec = get_interface_spec("fsl.bet", CORE_TOOL_TO_INTERFACE)
        assert spec is not None
        assert spec["type"] == "fsl"
        assert spec["name"] == "BET"

    def test_get_interface_spec_with_prefix(self):
        spec = get_interface_spec("mri.fsl.bet", CORE_TOOL_TO_INTERFACE)
        assert spec is not None
        assert spec["type"] == "fsl"

    def test_get_interface_spec_unknown_tool(self):
        spec = get_interface_spec("unknown.tool", CORE_TOOL_TO_INTERFACE)
        assert spec is None

    def test_load_tool_interface_map_returns_dict(self):
        mapping = load_tool_interface_map()
        assert isinstance(mapping, dict)
        assert len(mapping) > 0

    def test_io_map_structure(self):
        spec = CORE_TOOL_TO_INTERFACE["fsl.bet"]
        assert "io_map" in spec
        assert "consumes" in spec["io_map"]
        assert "produces" in spec["io_map"]
        assert "in" in spec["io_map"]["consumes"]
        assert "out" in spec["io_map"]["produces"]


class TestMapStepToNode:
    """Tests for step-to-node conversion."""

    @pytest.fixture
    def interface_map(self):
        return load_tool_interface_map()

    def test_known_tool_creates_interface_node(self, interface_map):
        step = StepSpec(
            id="step-001",
            tool="fsl.bet",
            consumes={"in": "volume_3d"},
            produces={"out": "volume_3d"},
            params={"frac": 0.4},
        )
        node_config, warning = _map_step_to_node(step, interface_map)

        assert node_config is not None
        assert node_config["name"] == "step_001"
        assert node_config["interface"]["type"] == "fsl"
        assert node_config["interface"]["name"] == "BET"
        assert node_config["interface"]["params"]["frac"] == 0.4
        assert warning is None

    def test_unknown_tool_creates_identity_node(self, interface_map):
        step = StepSpec(
            id="step-002",
            tool="unknown.custom_tool",
            consumes={"input": "volume_3d"},
            produces={"output": "volume_3d"},
            params={},
        )
        node_config, warning = _map_step_to_node(step, interface_map)

        assert node_config is not None
        assert node_config["name"] == "step_002"
        assert "fields" in node_config  # IdentityInterface uses fields
        assert warning is not None
        assert "No interface mapping" in warning


class TestDeriveConnections:
    """Tests for DAG connection derivation."""

    @pytest.fixture
    def interface_map(self):
        return load_tool_interface_map()

    def test_matching_resource_creates_connection(self, interface_map):
        steps = [
            StepSpec(
                id="step-001",
                tool="fsl.bet",
                consumes={"input": "volume_3d"},
                produces={"preprocessed": "volume_3d"},
            ),
            StepSpec(
                id="step-002",
                tool="fsl.smooth",
                consumes={"preprocessed": "volume_3d"},
                produces={"output": "volume_3d"},
            ),
        ]
        step_to_node = {"step-001": "step_001", "step-002": "step_002"}

        connections, warnings = _derive_connections(steps, step_to_node, interface_map)

        assert len(connections) == 1
        from_node, from_field, to_node, to_field = connections[0]
        assert from_node == "step_001"
        assert to_node == "step_002"

    def test_no_connection_for_unmatched_resources(self, interface_map):
        steps = [
            StepSpec(
                id="step-001",
                tool="fsl.bet",
                produces={"output_a": "volume_3d"},
            ),
            StepSpec(
                id="step-002",
                tool="fsl.smooth",
                consumes={"input_b": "volume_3d"},  # Different name
            ),
        ]
        step_to_node = {"step-001": "step_001", "step-002": "step_002"}

        connections, warnings = _derive_connections(steps, step_to_node, interface_map)

        assert len(connections) == 1
        assert any("linear step connections" in w for w in warnings)

    def test_warns_on_duplicate_producer(self, interface_map):
        steps = [
            StepSpec(
                id="step-001",
                tool="fsl.bet",
                produces={"data": "volume_3d"},
            ),
            StepSpec(
                id="step-002",
                tool="fsl.smooth",
                produces={"data": "volume_3d"},  # Same resource name
            ),
            StepSpec(
                id="step-003",
                tool="fsl.flirt",
                consumes={"data": "volume_3d"},
            ),
        ]
        step_to_node = {
            "step-001": "step_001",
            "step-002": "step_002",
            "step-003": "step_003",
        }

        connections, warnings = _derive_connections(steps, step_to_node, interface_map)

        assert any("multiple steps" in w for w in warnings)

    def test_linear_fallback_connection(self, interface_map):
        steps = [
            StepSpec(
                id="step-001",
                tool="fsl.bet",
            ),
            StepSpec(
                id="step-002",
                tool="fsl.smooth",
            ),
        ]
        step_to_node = {"step-001": "step_001", "step-002": "step_002"}

        connections, warnings = _derive_connections(steps, step_to_node, interface_map)

        assert len(connections) == 1
        assert any("linear step connections" in w for w in warnings)


class TestPlanToNipypeBuilderArgs:
    """Tests for the main conversion function."""

    @pytest.fixture
    def simple_plan(self) -> Plan:
        return Plan(
            plan_id="test-plan-001",
            domain="neuroimaging",
            modality=["fmri"],
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="step-001",
                        tool="fsl.bet",
                        consumes={"input": "volume_3d"},
                        produces={"brain": "volume_3d"},
                        params={"frac": 0.5},
                        runtime_kind="container",
                    ),
                    StepSpec(
                        id="step-002",
                        tool="fsl.smooth",
                        consumes={"brain": "volume_3d"},
                        produces={"smoothed": "volume_3d"},
                        params={"fwhm": 6.0},
                        runtime_kind="container",
                    ),
                ],
                artifacts=[],
            ),
        )

    def test_basic_conversion(self, simple_plan):
        result = plan_to_nipype_builder_args(
            plan=simple_plan,
            base_dir="/tmp/test",
            plugin="MultiProc",
        )

        assert isinstance(result, NipypeExportResult)
        assert result.plan_id == "test-plan-001"
        assert len(result.exported_steps) == 2
        assert len(result.skipped_steps) == 0

        args = result.builder_args
        assert args["name"] == "plan_test_plan_001"
        assert args["base_dir"] == "/tmp/test"
        assert args["plugin"] == "MultiProc"
        assert len(args["nodes"]) == 2

    def test_connections_derived(self, simple_plan):
        result = plan_to_nipype_builder_args(
            plan=simple_plan,
            base_dir="/tmp/test",
        )

        connections = result.builder_args["connections"]
        assert len(connections) == 1  # brain resource connects the two steps

    def test_skips_api_runtime_kind(self):
        plan = Plan(
            plan_id="api-plan",
            domain="neuroimaging",
            modality=["fmri"],
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="api-step",
                        tool="external.api.call",
                        runtime_kind="api",
                    ),
                ],
            ),
        )

        result = plan_to_nipype_builder_args(
            plan=plan,
            base_dir="/tmp/test",
            strict=False,
        )

        assert "api-step" in result.skipped_steps
        assert len(result.exported_steps) == 0
        assert any("api" in w.lower() for w in result.warnings)

    def test_strict_mode_raises_for_unsupported(self):
        plan = Plan(
            plan_id="api-plan",
            domain="neuroimaging",
            modality=["fmri"],
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="api-step",
                        tool="external.api.call",
                        runtime_kind="api",
                    ),
                ],
            ),
        )

        with pytest.raises(ValueError, match="unsupported runtime_kind"):
            plan_to_nipype_builder_args(
                plan=plan,
                base_dir="/tmp/test",
                strict=True,
            )

    def test_step_to_node_mapping(self, simple_plan):
        result = plan_to_nipype_builder_args(
            plan=simple_plan,
            base_dir="/tmp/test",
        )

        assert "step-001" in result.step_to_node
        assert "step-002" in result.step_to_node
        assert result.step_to_node["step-001"] == "step_001"
        assert result.step_to_node["step-002"] == "step_002"

    def test_plugin_args_passed_through(self, simple_plan):
        result = plan_to_nipype_builder_args(
            plan=simple_plan,
            base_dir="/tmp/test",
            plugin="MultiProc",
            plugin_args={"n_procs": 4, "memory_gb": 8},
        )

        assert result.builder_args["plugin_args"]["n_procs"] == 4
        assert result.builder_args["plugin_args"]["memory_gb"] == 8


class TestRuntimeKindSupport:
    """Tests for runtime kind handling."""

    def test_container_is_supported(self):
        assert "container" in SUPPORTED_RUNTIME_KINDS

    def test_python_is_supported(self):
        assert "python" in SUPPORTED_RUNTIME_KINDS

    def test_api_is_unsupported(self):
        assert "api" in UNSUPPORTED_RUNTIME_KINDS


class TestNipypeExportResult:
    """Tests for NipypeExportResult dataclass."""

    def test_to_dict(self):
        result = NipypeExportResult(
            builder_args={"name": "test", "nodes": []},
            plan_id="test-plan",
            exported_steps=["step-001"],
            skipped_steps=["step-002"],
            warnings=["Some warning"],
            step_to_node={"step-001": "step_001"},
        )

        d = result.to_dict()

        assert d["plan_id"] == "test-plan"
        assert d["exported_steps"] == ["step-001"]
        assert d["skipped_steps"] == ["step-002"]
        assert d["warnings"] == ["Some warning"]
        assert d["step_to_node"] == {"step-001": "step_001"}
        assert "builder_args" in d
