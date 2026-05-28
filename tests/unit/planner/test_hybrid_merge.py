"""Tests for hybrid merge of container and Python tools."""

import os
import pytest
from unittest.mock import patch

from brain_researcher.services.agent.planner.catalog_loader import (
    ToolCapability,
    ToolSpec,
    ResourceSpec,
    PythonRunnerSpec,
    legacy_tool_to_capability,
    enrich_and_merge,
    get_capability_index,
    get_tool_by_id,
    search_by_capability,
    search_by_modality,
    load_capabilities_yaml,
    load_tools_catalog_json,
    load_niwrap_containers,
)
class TestLegacyConversion:
    """Test conversion of legacy tools to ToolCapability."""

    def test_legacy_tool_to_capability_basic(self):
        """Test basic legacy tool conversion."""
        spec = ToolSpec(
            name="extract_timeseries",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"fmri_img": "volume_4d", "atlas": "parcellation_labels"},
            produces={"timeseries": "timeseries"},
            constraints={"cpu_min": 2, "mem_mb_min": 1024},
        )

        capability = legacy_tool_to_capability("extract_timeseries", spec)

        assert capability.runtime_kind == "python"
        assert capability.id == "python.neuroimaging.extract_timeseries"
        assert capability.package == "python"
        assert capability.python is not None
        assert capability.container is None
        assert "fmri" in capability.modality
        assert "timeseries" in capability.produces

    def test_legacy_tool_resource_defaults(self):
        """Test that legacy tools get sensible resource defaults."""
        spec = ToolSpec(
            name="test_tool",
            domain="neuroimaging",
            modality=["smri"],
            consumes={"img": "volume_3d"},
            produces={"out": "volume_3d"},
            constraints={},  # No resource constraints
        )

        capability = legacy_tool_to_capability("test_tool", spec)

        # Should have default resources
        assert capability.resources.cpu_min == 1
        assert capability.resources.mem_mb_min == 512
        assert capability.resources.gpu is False
        assert capability.resources.time_min_default == 5.0

    def test_legacy_tool_python_spec(self):
        """Test that Python spec is created correctly."""
        spec = ToolSpec(
            name="nilearn_connectivity_matrix",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"ts": "timeseries"},
            produces={"matrix": "connectivity_matrix"},
        )

        capability = legacy_tool_to_capability("nilearn_connectivity_matrix", spec)

        assert capability.python.module == "brain_researcher.services.neuroimaging"
        assert capability.python.function == "nilearn_connectivity_matrix"
        assert capability.python.entry_type == "function"


class TestHybridMerge:
    """Test hybrid merge of container and Python tools."""

    def test_merge_includes_both_types(self):
        """Test that merge includes both container and Python tools."""
        # Create sample container tool
        container_tool = ToolCapability(
            id="fsl.test.run",
            name="Test Tool",
            package="fsl",
            runtime_kind="container",
            entrypoint="fsl.test",
            modality=["smri"],
            capabilities=["test"],
            consumes=["volume_3d"],
            produces=["volume_3d"],
            resources=ResourceSpec(cpu_min=1, mem_mb_min=512, gpu=False, time_min_default=2.0),
            container={"package_ref": "fsl", "runtime": "apptainer"},
        )

        # Create sample legacy tool
        legacy_spec = ToolSpec(
            name="test_python",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"img": "volume_4d"},
            produces={"out": "timeseries"},
        )

        # Merge
        result = enrich_and_merge(
            capabilities=[container_tool],
            legacy_tools={"test_python": legacy_spec},
            resources={},
            containers={},
        )

        # Should have both tools
        assert len(result) == 2
        assert any(t.runtime_kind == "container" for t in result)
        assert any(t.runtime_kind == "python" for t in result)

    def test_merge_respects_include_legacy_flag(self):
        """Test that BR_PLANNER_INCLUDE_LEGACY flag works."""
        container_tool = ToolCapability(
            id="fsl.test.run",
            name="Test Tool",
            package="fsl",
            runtime_kind="container",
            entrypoint="fsl.test",
            modality=["smri"],
            capabilities=["test"],
            consumes=["volume_3d"],
            produces=["volume_3d"],
            resources=ResourceSpec(cpu_min=1, mem_mb_min=512, gpu=False, time_min_default=2.0),
            container={"package_ref": "fsl", "runtime": "apptainer"},
        )

        legacy_spec = ToolSpec(
            name="test_python",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"img": "volume_4d"},
            produces={"out": "timeseries"},
        )

        # Test with legacy disabled
        with patch.dict(os.environ, {"BR_PLANNER_INCLUDE_LEGACY": "false"}):
            result = enrich_and_merge(
                capabilities=[container_tool],
                legacy_tools={"test_python": legacy_spec},
                resources={},
                containers={},
            )
            # Should only have container tool
            assert len(result) == 1
            assert result[0].runtime_kind == "container"

        # Test with legacy enabled (default)
        with patch.dict(os.environ, {"BR_PLANNER_INCLUDE_LEGACY": "true"}):
            result = enrich_and_merge(
                capabilities=[container_tool],
                legacy_tools={"test_python": legacy_spec},
                resources={},
                containers={},
            )
            # Should have both
            assert len(result) == 2


class TestCatalogMode:
    """Test catalog mode end-to-end."""

    def test_catalog_mode_loads_both_types(self):
        """Test that catalog mode loads both container and Python tools."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            # Clear cache
            get_capability_index.cache_clear()

            index = get_capability_index()

            # Should have tools from both sources
            assert len(index.by_id) > 14  # More than just container tools

            # Count by runtime
            container_count = sum(1 for t in index.by_id.values() if t.runtime_kind == "container")
            python_count = sum(1 for t in index.by_id.values() if t.runtime_kind == "python")

            assert container_count >= 14  # At least the 14 we defined
            assert python_count > 0  # Should have Python tools too

    def test_legacy_tools_absent_in_legacy_mode(self):
        """Test that catalog mode is required for hybrid loading."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "legacy"}):
            # Clear cache
            get_capability_index.cache_clear()

            index = get_capability_index()

            # Legacy mode should return empty index
            assert len(index.by_id) == 0

    def test_all_legacy_tools_converted(self):
        """Test that all legacy tools are converted in catalog mode."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog", "BR_PLANNER_INCLUDE_LEGACY": "true"}):
            get_capability_index.cache_clear()

            # Load legacy tools directly
            legacy_tools = load_tools_catalog_json()
            legacy_count = len(legacy_tools)

            # Load via catalog
            index = get_capability_index()
            legacy_python = [t for t in index.by_id.values() if t.source == "legacy"]

            # All legacy tools should be converted.
            assert len(legacy_python) == legacy_count

    def test_search_returns_both_types(self):
        """Test that search functions return both container and Python tools."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            get_capability_index.cache_clear()

            # Search by modality that exists in both types
            fmri_tools = search_by_modality("fmri")

            # Should have both types
            runtime_kinds = {t.runtime_kind for t in fmri_tools}
            assert "container" in runtime_kinds
            assert "python" in runtime_kinds


class TestPythonToolProperties:
    """Test properties of converted Python tools."""

    def test_python_tools_have_correct_structure(self):
        """Test that Python tools have required fields."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            get_capability_index.cache_clear()

            index = get_capability_index()
            python_tools = [t for t in index.by_id.values() if t.runtime_kind == "python"]

            assert len(python_tools) > 0

            for tool in python_tools:
                # Required fields
                assert tool.runtime_kind == "python"
                assert tool.python is not None
                assert tool.container is None
                assert tool.entrypoint is None or tool.entrypoint == ""

                # Python spec
                assert tool.python.module
                assert tool.python.function
                assert tool.python.entry_type in ["function", "class"]

                # Resources
                assert tool.resources.cpu_min >= 1
                assert tool.resources.mem_mb_min >= 128

    def test_python_tool_ids_follow_pattern(self):
        """Test that Python tool IDs follow python.domain.name pattern."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            get_capability_index.cache_clear()

            index = get_capability_index()
            python_tools = [t for t in index.by_id.values() if t.runtime_kind == "python"]

            for tool in python_tools:
                assert tool.id.startswith(("python.", "ai.", "code.", "google.")), tool.id
                parts = tool.id.split(".")
                assert len(parts) >= 2  # allow ai.llm.* etc.


class TestContainerToolCompatibility:
    """Test that existing container tools still work."""

    def test_container_tools_unchanged(self):
        """Test that container tools maintain their structure."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            get_capability_index.cache_clear()

            index = get_capability_index()
            tool = next(
                t
                for t in index.by_id.values()
                if t.runtime_kind == "container" and t.container is not None
            )
            tool = get_tool_by_id(tool.id)
            assert tool is not None
            assert tool.runtime_kind == "container"
            assert tool.container is not None
            assert tool.python is None
            assert tool.entrypoint is not None
            assert tool.container.package_ref


class TestResourceEnumSync:
    """Test that resource types are properly synchronized."""

    def test_python_tools_use_valid_resource_types(self):
        """Test that Python tools only use valid resource types."""
        from brain_researcher.services.shared.planner.models import ResourceType as ValidTypes
        # Get all valid resource types
        valid_types = ValidTypes.get_allowed()

        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            get_capability_index.cache_clear()

            index = get_capability_index()
            python_tools = [t for t in index.by_id.values() if t.runtime_kind == "python"]

            for tool in python_tools:
                # All consumes/produces should be valid
                for resource in tool.consumes + tool.produces:
                    assert resource in valid_types, f"Invalid resource type {resource} in tool {tool.id}"


class TestConsumesProducesConversion:
    """Test detailed consumes/produces conversion from legacy to capability."""

    def test_single_input_output_conversion(self):
        """Test simple consumes/produces with single I/O."""
        spec = ToolSpec(
            name="simple_tool",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"input_image": "volume_4d"},
            produces={"output_timeseries": "timeseries"},
        )

        capability = legacy_tool_to_capability("simple_tool", spec)

        # Verify conversion from dict to list format
        assert "volume_4d" in capability.consumes
        assert "timeseries" in capability.produces
        assert len(capability.consumes) == 1
        assert len(capability.produces) == 1

    def test_multiple_inputs_outputs_conversion(self):
        """Test consumes/produces with multiple inputs and outputs."""
        spec = ToolSpec(
            name="complex_tool",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={
                "fmri_img": "volume_4d",
                "atlas": "parcellation_labels",
                "mask": "mask_path",
                "events": "events_tsv",
            },
            produces={
                "timeseries": "timeseries",
                "connectivity": "connectivity_matrix",
                "report": "report_html",
            },
        )

        capability = legacy_tool_to_capability("complex_tool", spec)

        # All consumes should be preserved
        assert "volume_4d" in capability.consumes
        assert "parcellation_labels" in capability.consumes
        assert "mask_path" in capability.consumes
        assert "events_tsv" in capability.consumes
        assert len(capability.consumes) == 4

        # All produces should be preserved
        assert "timeseries" in capability.produces
        assert "connectivity_matrix" in capability.produces
        assert "report_html" in capability.produces
        assert len(capability.produces) == 3

    def test_empty_consumes_produces(self):
        """Test handling of tools with no inputs or outputs."""
        spec = ToolSpec(
            name="no_io_tool",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={},
            produces={},
        )

        capability = legacy_tool_to_capability("no_io_tool", spec)

        # Should have empty lists, not None
        assert capability.consumes == []
        assert capability.produces == []

    def test_consumes_produces_preserve_resource_types(self):
        """Test that all resource types are correctly preserved during conversion."""
        # Test various resource types from the shared models
        spec = ToolSpec(
            name="multimodal_tool",
            domain="neuroimaging",
            modality=["fmri", "smri", "dmri"],
            consumes={
                "t1w": "volume_3d",
                "bold": "volume_4d",
                "surface": "surface_mesh",
                "parcellation": "parcellation_labels",
                "mask": "mask_path",
                "bvals": "bvals",
                "bvecs": "bvecs",
            },
            produces={
                "stat_map": "stat_map",
                "connectivity": "connectivity_matrix",
                "table": "features_table",
            },
        )

        capability = legacy_tool_to_capability("multimodal_tool", spec)

        # Verify all input types preserved
        expected_consumes = {
            "volume_3d",
            "volume_4d",
            "surface_mesh",
            "parcellation_labels",
            "mask_path",
            "bvals",
            "bvecs",
        }
        assert set(capability.consumes) == expected_consumes

        # Verify all output types preserved
        expected_produces = {"stat_map", "connectivity_matrix", "features_table"}
        assert set(capability.produces) == expected_produces

    def test_duplicate_resource_types_in_conversion(self):
        """Test that duplicate resource types in consumes/produces are handled."""
        spec = ToolSpec(
            name="duplicate_io_tool",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={
                "img1": "volume_4d",
                "img2": "volume_4d",  # Duplicate type
                "img3": "volume_4d",  # Duplicate type
            },
            produces={
                "out1": "timeseries",
                "out2": "timeseries",  # Duplicate type
            },
        )

        capability = legacy_tool_to_capability("duplicate_io_tool", spec)

        # Lists may contain duplicates (valid for multiple inputs of same type)
        assert capability.consumes.count("volume_4d") == 3
        assert capability.produces.count("timeseries") == 2

    def test_consumes_produces_in_merged_catalog(self):
        """Test that consumes/produces survive the merge process."""
        legacy_spec = ToolSpec(
            name="connectivity_tool",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"timeseries": "timeseries", "atlas": "parcellation_labels"},
            produces={"matrix": "connectivity_matrix"},
        )

        result = enrich_and_merge(
            capabilities=[],
            legacy_tools={"connectivity_tool": legacy_spec},
            resources={},
            containers={},
        )

        # Find the converted tool
        python_tool = next(t for t in result if t.runtime_kind == "python")

        # Verify I/O preserved through merge
        assert "timeseries" in python_tool.consumes
        assert "parcellation_labels" in python_tool.consumes
        assert "connectivity_matrix" in python_tool.produces

    def test_consumes_produces_unique_across_tools(self):
        """Test that different tools have correctly isolated consumes/produces."""
        spec1 = ToolSpec(
            name="tool_a",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"img": "volume_4d"},
            produces={"ts": "timeseries"},
        )

        spec2 = ToolSpec(
            name="tool_b",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"ts": "timeseries"},
            produces={"conn": "connectivity_matrix"},
        )

        cap1 = legacy_tool_to_capability("tool_a", spec1)
        cap2 = legacy_tool_to_capability("tool_b", spec2)

        # Verify no cross-contamination
        assert cap1.consumes == ["volume_4d"]
        assert cap1.produces == ["timeseries"]
        assert cap2.consumes == ["timeseries"]
        assert cap2.produces == ["connectivity_matrix"]

        # Verify tool1's produces matches tool2's consumes (pipeline compatibility)
        assert cap1.produces[0] == cap2.consumes[0]

    def test_real_world_pipeline_io_chain(self):
        """Test realistic pipeline: fetch → extract → analyze."""
        # Step 1: Fetch atlas (no input, produces parcellation)
        fetch_spec = ToolSpec(
            name="fetch_atlas",
            domain="neuroimaging",
            modality=["smri"],
            consumes={},
            produces={"atlas": "parcellation_labels"},
        )

        # Step 2: Extract timeseries (fMRI + atlas → timeseries)
        extract_spec = ToolSpec(
            name="extract_timeseries",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"fmri": "volume_4d", "atlas": "parcellation_labels"},
            produces={"ts": "timeseries"},
        )

        # Step 3: Compute connectivity (timeseries → matrix)
        connect_spec = ToolSpec(
            name="nilearn_connectivity_matrix",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"timeseries": "timeseries"},
            produces={"connectivity": "connectivity_matrix"},
        )

        # Convert all
        fetch_cap = legacy_tool_to_capability("fetch_atlas", fetch_spec)
        extract_cap = legacy_tool_to_capability("extract_timeseries", extract_spec)
        connect_cap = legacy_tool_to_capability("nilearn_connectivity_matrix", connect_spec)

        # Verify pipeline chain integrity
        assert fetch_cap.consumes == []
        assert "parcellation_labels" in fetch_cap.produces

        assert "volume_4d" in extract_cap.consumes
        assert "parcellation_labels" in extract_cap.consumes
        assert "timeseries" in extract_cap.produces

        assert "timeseries" in connect_cap.consumes
        assert "connectivity_matrix" in connect_cap.produces

        # Verify data flows: fetch.produces → extract.consumes
        assert fetch_cap.produces[0] in extract_cap.consumes

        # Verify data flows: extract.produces → connect.consumes
        assert extract_cap.produces[0] in connect_cap.consumes
