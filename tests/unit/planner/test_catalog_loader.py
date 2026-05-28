"""Unit tests for catalog_loader module."""

import os
import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch

from brain_researcher.services.agent.planner import catalog_loader
from brain_researcher.services.agent.planner.catalog_loader import (
    ToolCapability,
    ToolSpec,
    ResourceSpec,
    ContainerSpec,
    CapabilityIndex,
    legacy_tool_to_capability,
    load_capabilities_yaml,
    load_tools_catalog_json,
    load_niwrap_containers,
    load_niwrap_mapping,
    enrich_tool_with_container_info,
    enrich_and_merge,
    build_indexes,
    get_capability_index,
    get_tool_by_id,
    search_by_capability,
    search_by_modality,
    search_by_package,
    get_planner_source,
)


class TestModels:
    """Test Pydantic models."""

    def test_resource_spec_validation(self):
        """Test ResourceSpec validation."""
        # Valid spec
        spec = ResourceSpec(
            cpu_min=2, mem_mb_min=2048, gpu=False, time_min_default=10.0
        )
        assert spec.cpu_min == 2
        assert spec.mem_mb_min == 2048
        assert spec.gpu is False

        # Invalid: CPU too high
        with pytest.raises(Exception):
            ResourceSpec(
                cpu_min=100, mem_mb_min=2048, gpu=False, time_min_default=10.0
            )

        # Invalid: Memory too low
        with pytest.raises(Exception):
            ResourceSpec(cpu_min=2, mem_mb_min=50, gpu=False, time_min_default=10.0)

    def test_container_spec_validation(self):
        """Test ContainerSpec validation."""
        spec = ContainerSpec(package_ref="fsl", runtime="apptainer")
        assert spec.package_ref == "fsl"
        assert spec.runtime == "apptainer"
        assert spec.network_disabled is True
        assert spec.require_license is False

    def test_tool_capability_validation(self):
        """Test ToolCapability validation."""
        # Valid tool
        tool = ToolCapability(
            id="fsl_bet",
            name="FSL BET",
            package="fsl",
            runtime_kind="container",
            entrypoint="fsl.6.0.7.bet.run",
            modality=["smri"],
            capabilities=["skull_strip"],
            consumes=["volume_3d"],
            produces=["volume_3d", "mask_path"],
            resources=ResourceSpec(
                cpu_min=1, mem_mb_min=512, gpu=False, time_min_default=2.0
            ),
            container=ContainerSpec(package_ref="fsl", runtime="apptainer"),
        )
        assert tool.id == "fsl_bet"
        assert "skull_strip" in tool.capabilities

        # Invalid: Bad ID format
        with pytest.raises(Exception):
            ToolCapability(
                id="bad id",  # whitespace is not allowed
                name="Test",
                package="test",
                runtime_kind="container",
                entrypoint="test.run",
                modality=["smri"],
                capabilities=["test"],
                consumes=["volume_3d"],
                produces=["volume_3d"],
                resources=ResourceSpec(
                    cpu_min=1, mem_mb_min=512, gpu=False, time_min_default=2.0
                ),
                container=ContainerSpec(package_ref="test", runtime="apptainer"),
            )

    def test_tool_spec_python_fields(self):
        """ToolSpec supports python runner metadata with default runtime."""

        spec = ToolSpec(
            name="python_tool",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"atlas": "parcellation_labels"},
            produces={"timeseries": "timeseries"},
            python_module="brain_researcher.services.tools.fetch_atlas_tool",
            python_function="FetchAtlasTool",
            runtime_kind="python",
        )

        assert spec.runtime_kind == "python"
        assert spec.python_module.endswith("fetch_atlas_tool")
        assert spec.python_function == "FetchAtlasTool"

    def test_tool_spec_defaults_to_container(self):
        spec = ToolSpec(
            name="container_tool",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"img": "volume_4d"},
            produces={"mask": "mask_path"},
        )
        assert spec.runtime_kind == "container"

    def test_duplicate_catalog_ids_raise(self):
        """Capabilities.yaml duplicates should fail fast."""
        res = ResourceSpec(cpu_min=1, mem_mb_min=256, gpu=False, time_min_default=1.0)
        cap1 = ToolCapability(
            id="dup.tool",
            name="dup1",
            package="pkg",
            runtime_kind="container",
            entrypoint="pkg.v1.tool",
            modality=["fmri"],
            capabilities=["test"],
            consumes=["volume_4d"],
            produces=["mask_path"],
            resources=res,
            container=ContainerSpec(package_ref="pkg", runtime="apptainer"),
        )
        cap2 = cap1.model_copy()
        with pytest.raises(ValueError):
            enrich_and_merge(
                [cap1, cap2],
                legacy_tools={},
                resources={},
                mapping={},
                containers={},
                include_niwrap=False,
            )

    def test_legacy_python_missing_metadata_warns(self, caplog):
        """Python legacy tool without module/function should raise and warn."""
        legacy_spec = ToolSpec(
            name="py_bad",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"input": "volume_4d"},
            produces={"out": "mask_path"},
            runtime_kind="python",
        )
        cap = legacy_tool_to_capability("py_bad", legacy_spec)
        assert cap.python is not None
        # Default module/function should be auto-populated
        assert cap.python.module
        assert cap.python.function

    def test_catalog_wins_over_legacy_conflict(self, caplog):
        """Catalog tool should override legacy tool with same resolved id."""
        cap = ToolCapability(
            id="neuroimaging.id",
            name="catalog-tool",
            package="pkg",
            runtime_kind="container",
            entrypoint="pkg.v1.tool",
            modality=["fmri"],
            capabilities=["test"],
            consumes=["volume_4d"],
            produces=["mask_path"],
            resources=ResourceSpec(cpu_min=1, mem_mb_min=256, gpu=False, time_min_default=1.0),
            container=ContainerSpec(package_ref="pkg", runtime="apptainer"),
        )
        legacy_spec = ToolSpec(
            name="legacy.id",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"input": "volume_4d"},
            produces={"out": "mask_path"},
            runtime_kind="container",
        )
        merged = enrich_and_merge(
            [cap],
            legacy_tools={"id": legacy_spec},
            resources={},
            mapping={},
            containers={"pkg": {"image": "/tmp/img.sif", "runtime": "apptainer"}},
            include_niwrap=False,
        )
        ids = [t.id for t in merged]
        assert "neuroimaging.id" in ids
        # Catalog entry should win on conflict for the same id
        catalog_tool = next(t for t in merged if t.id == "neuroimaging.id")
        assert catalog_tool.name == "catalog-tool"
    def test_all_python_tools_have_metadata(self):
        """Every python tool in tools_catalog.json must declare module and function."""
        tools = load_tools_catalog_json()
        python_tools = [t for t in tools.values() if t.runtime_kind == "python"]
        assert python_tools, "Expected at least one python tool in tools_catalog.json"
        missing = [
            t.name
            for t in python_tools
            if not t.python_module or not t.python_function
        ]
        assert not missing, f"Python tools missing metadata: {missing}"


class TestLoaders:
    """Test loader functions."""

    def test_load_capabilities_yaml(self):
        """Test loading capabilities.yaml."""
        tools = load_capabilities_yaml()
        assert len(tools) > 0
        assert all(isinstance(t, ToolCapability) for t in tools)

        # Check some expected tools
        tool_ids = [t.id for t in tools]
        assert "fsl.bet.run" in tool_ids

    def test_load_tools_catalog_json(self):
        """Test loading tools_catalog.json."""
        tools = load_tools_catalog_json()
        assert len(tools) > 0
        assert all(isinstance(t, ToolSpec) for t in tools.values())
        # spot-check python runner fields exist
        py_tool = tools.get("fetch_atlas")
        assert py_tool
        assert py_tool.runtime_kind == "python"
        assert py_tool.python_module

    def test_load_tools_catalog_json_falls_back_to_merged(self, tmp_path, monkeypatch):
        """Load merged catalog when the legacy JSON file is absent."""
        repo_root = tmp_path / "repo"
        config_dir = repo_root / "configs"
        config_dir.mkdir(parents=True)

        source = Path(__file__).resolve().parents[3] / "configs" / "tools_catalog_merged.json"
        shutil.copyfile(source, config_dir / "tools_catalog_merged.json")

        monkeypatch.setattr(catalog_loader, "get_repo_root", lambda: repo_root)

        tools = load_tools_catalog_json()
        assert "fetch_atlas" in tools
        assert "extract_timeseries" in tools

        fetch_atlas = tools["fetch_atlas"]
        assert fetch_atlas.runtime_kind == "python"
        assert fetch_atlas.python_module == "brain_researcher.services.tools.fetch_atlas_tool"
        assert fetch_atlas.python_function == "fetch_atlas"
        assert fetch_atlas.domain == "neuroimaging"
        assert fetch_atlas.modality == ["general"]

        extract_timeseries = tools["extract_timeseries"]
        assert extract_timeseries.runtime_kind == "python"
        assert extract_timeseries.modality == ["dmri"]
        assert extract_timeseries.python_function == "extract_timeseries"

    def test_tools_catalog_schema_validation(self):
        """Validate tools_catalog.json against JSON schema."""
        jsonschema = pytest.importorskip("jsonschema")
        schema_path = Path("configs/schemas/tools_catalog.schema.json")
        data_path = Path("configs/tools_catalog.json")
        schema = json.loads(schema_path.read_text())
        instance = json.loads(data_path.read_text())
        jsonschema.validate(instance=instance, schema=schema)

    def test_load_niwrap_containers(self):
        """Test loading niwrap_containers.yaml."""
        containers = load_niwrap_containers()
        assert len(containers) > 0
        assert "fsl" in containers
        assert "image" in containers["fsl"]
        assert "runtime" in containers["fsl"]

    def test_enrich_tool_with_container_info(self):
        """Test enriching tool with container metadata."""
        tool = ToolCapability(
            id="fsl.test.run",
            name="Test Tool",
            package="fsl",
            runtime_kind="container",
            entrypoint="fsl.test",
            modality=["smri"],
            capabilities=["test"],
            consumes=["volume_3d"],
            produces=["volume_3d"],
            resources=ResourceSpec(
                cpu_min=1, mem_mb_min=512, gpu=False, time_min_default=2.0
            ),
            container=ContainerSpec(package_ref="fsl", runtime="apptainer"),
        )

        containers = {
            "fsl": {
                "image": "/path/to/fsl.simg",
                "binds": ["/data:/data"],
                "env": {"FSLOUTPUTTYPE": "NIFTI_GZ"},
                "network_disabled": True,
            }
        }

        enriched = enrich_tool_with_container_info(tool, containers)
        assert enriched.container.image == "/path/to/fsl.simg"
        assert enriched.container.binds == ["/data:/data"]
        assert enriched.container.env["FSLOUTPUTTYPE"] == "NIFTI_GZ"

    def test_generated_catalog_merges_with_curated_preferring_curated(self, tmp_path):
        # curated file with one tool
        curated = tmp_path / "curated.yaml"
        curated.write_text(
            """
tools:
  - id: fsl.bet.run
    name: BET curated
    package: fsl
    runtime_kind: container
    entrypoint: fsl.bet
    modality: [smri]
    capabilities: [skull_strip]
    consumes: []
    produces: []
    resources: {cpu_min: 1, mem_mb_min: 512, gpu: false, time_min_default: 2.0}
"""
        )

        generated = tmp_path / "generated.yaml"
        generated.write_text(
            """
tools:
  - id: fsl.bet.run
    name: BET generated
    package: fsl
    runtime_kind: container
    entrypoint: fsl.bet
    modality: [fmri]
    capabilities: [auto]
    consumes: []
    produces: []
    resources: {cpu_min: 1, mem_mb_min: 512, gpu: false, time_min_default: 5.0}
  - id: afni.bandpass.run
    name: AFNI bandpass
    package: afni
    runtime_kind: container
    entrypoint: afni.bandpass
    modality: [fmri]
    capabilities: [preprocessing]
    consumes: []
    produces: []
    resources: {cpu_min: 1, mem_mb_min: 512, gpu: false, time_min_default: 5.0}
"""
        )

        tools = catalog_loader.load_capabilities_yaml(
            path=curated, generated_paths=[generated]
        )

        by_id = {t.id: t for t in tools}
        assert by_id["fsl.bet.run"].name == "BET curated"  # curated wins
        assert "afni.bandpass.run" in by_id

    def test_legacy_tool_to_capability_uses_python_fields(self):
        spec = ToolSpec(
            name="extract_timeseries",
            domain="neuroimaging",
            modality=["fmri"],
            consumes={"atlas": "parcellation_labels"},
            produces={"ts": "timeseries"},
            runtime_kind="python",
            python_module="brain_researcher.services.tools.extract_timeseries_tool",
            python_function="ExtractTimeseriesTool",
        )

        cap = catalog_loader.legacy_tool_to_capability("extract_timeseries", spec)
        assert cap.runtime_kind == "python"
        assert cap.python is not None
        assert cap.python.module.endswith("extract_timeseries_tool")
        assert cap.python.function == "ExtractTimeseriesTool"


class TestIndexing:
    """Test indexing functionality."""

    def test_build_indexes(self):
        """Test building capability indexes."""
        tools = [
            ToolCapability(
                id="fsl.bet.run",
                name="BET",
                package="fsl",
                runtime_kind="container",
                entrypoint="fsl.bet",
                modality=["smri", "fmri"],
                capabilities=["skull_strip", "preprocessing"],
                consumes=["volume_3d"],
                produces=["volume_3d", "mask_path"],
                resources=ResourceSpec(
                    cpu_min=1, mem_mb_min=512, gpu=False, time_min_default=2.0
                ),
                container=ContainerSpec(package_ref="fsl", runtime="apptainer"),
            ),
            ToolCapability(
                id="ants.registration.run",
                name="ANTS Registration",
                package="ants",
                runtime_kind="container",
                entrypoint="ants.reg",
                modality=["smri"],
                capabilities=["registration", "nonlinear_registration"],
                consumes=["volume_3d"],
                produces=["volume_3d"],
                resources=ResourceSpec(
                    cpu_min=2, mem_mb_min=4096, gpu=False, time_min_default=30.0
                ),
                container=ContainerSpec(package_ref="ants", runtime="apptainer"),
            ),
        ]

        index = build_indexes(tools)

        # Check by_id
        assert "fsl.bet.run" in index.by_id
        assert "ants.registration.run" in index.by_id

        # Check by_capability
        assert "skull_strip" in index.by_capability
        assert "fsl.bet.run" in index.by_capability["skull_strip"]
        assert "registration" in index.by_capability
        assert "ants.registration.run" in index.by_capability["registration"]

        # Check by_modality
        assert "smri" in index.by_modality
        assert "fsl.bet.run" in index.by_modality["smri"]
        assert "ants.registration.run" in index.by_modality["smri"]
        assert "fmri" in index.by_modality
        assert "fsl.bet.run" in index.by_modality["fmri"]

        # Check by_package
        assert "fsl" in index.by_package
        assert "ants" in index.by_package
        assert len(index.by_package["fsl"]) == 1
        assert len(index.by_package["ants"]) == 1

        # Check by_resource_type
        assert "volume_3d" in index.by_resource_type
        assert "mask_path" in index.by_resource_type


class TestPublicAPI:
    """Test public API functions."""

    def test_get_planner_source(self):
        """Test getting planner source from environment."""
        # Default is catalog
        with patch.dict(os.environ, {}, clear=True):
            assert get_planner_source() == "catalog"

        # Can be set to catalog
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            assert get_planner_source() == "catalog"

        # Can be set to legacy
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "legacy"}):
            assert get_planner_source() == "legacy"

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [
            (None, "catalog"),  # default
            ("legacy", "legacy"),
            ("catalog", "catalog"),
            ("CATALOG", "catalog"),  # case-insensitive
        ],
    )
    def test_get_planner_source_parametrized(self, env_value, expected):
        """Explicit coverage of default/override/case-insensitive behavior."""
        context = {} if env_value is None else {"BR_PLANNER_SOURCE": env_value}
        with patch.dict(os.environ, context, clear=True):
            assert get_planner_source() == expected

    def test_get_capability_index_catalog_mode(self):
        """Test getting capability index in catalog mode."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            # Clear cache
            get_capability_index.cache_clear()

            index = get_capability_index()
            assert isinstance(index, CapabilityIndex)
            assert len(index.by_id) > 0

            legacy_tools = load_tools_catalog_json()
            legacy_name, legacy_spec = next(iter(legacy_tools.items()))
            expected_legacy = legacy_tool_to_capability(legacy_name, legacy_spec).id

            assert any(
                tool.runtime_kind == "container" for tool in index.by_id.values()
            )
            assert any(tool.runtime_kind == "python" for tool in index.by_id.values())
            assert expected_legacy in index.by_id

    def test_get_capability_index_legacy_mode(self):
        """Test getting capability index in legacy mode (empty)."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "legacy"}):
            # Clear cache
            get_capability_index.cache_clear()

            index = get_capability_index()
            assert isinstance(index, CapabilityIndex)
            assert len(index.by_id) == 0  # Empty in legacy mode

    def test_get_capability_index_catalog_fallback(self, caplog):
        """Catalog load errors fall back to empty index."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            get_capability_index.cache_clear()

            with patch.object(
                catalog_loader, "load_capabilities_yaml", side_effect=RuntimeError("boom")
            ):
                index = get_capability_index()

            assert isinstance(index, CapabilityIndex)
            assert len(index.by_id) == 0
            assert "Failed to load catalog assets" in caplog.text

    def test_get_tool_by_id(self):
        """Test getting tool by ID."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            # Clear cache
            get_capability_index.cache_clear()

            index = get_capability_index()
            expected_container = next(
                t.id for t in index.by_id.values() if t.runtime_kind == "container"
            )
            tool = get_tool_by_id(expected_container)
            assert tool is not None
            assert tool.id == expected_container
            assert tool.runtime_kind == "container"

            legacy_name, legacy_spec = next(
                (name, spec)
                for name, spec in load_tools_catalog_json().items()
                if spec.runtime_kind == "python"
            )
            expected_legacy = legacy_tool_to_capability(legacy_name, legacy_spec).id

            legacy_tool = get_tool_by_id(expected_legacy)
            assert legacy_tool is not None
            assert legacy_tool.runtime_kind == "python"

    def test_search_by_capability(self):
        """Test searching by capability tag."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            # Clear cache
            get_capability_index.cache_clear()

            index = get_capability_index()
            container_tool = next(
                t for t in index.by_id.values() if t.runtime_kind == "container" and t.capabilities
            )
            capability = container_tool.capabilities[0]
            tools = search_by_capability(capability)
            assert len(tools) > 0
            assert all(capability in t.capabilities for t in tools)

            legacy_tool = next(
                t for t in index.by_id.values() if t.runtime_kind == "python" and t.capabilities
            )
            legacy_capability = legacy_tool.capabilities[0]
            legacy_tools = search_by_capability(legacy_capability)
            assert len(legacy_tools) > 0

    def test_search_by_modality(self):
        """Test searching by modality."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            # Clear cache
            get_capability_index.cache_clear()

            tools = search_by_modality("fmri")
            assert len(tools) > 0
            assert all("fmri" in t.modality for t in tools)

            general_tools = search_by_modality("general")
            assert len(general_tools) > 0

    def test_search_by_package(self):
        """Test searching by package."""
        with patch.dict(os.environ, {"BR_PLANNER_SOURCE": "catalog"}):
            # Clear cache
            get_capability_index.cache_clear()

            tools = search_by_package("fsl")
            assert len(tools) > 0
            assert all(t.package == "fsl" for t in tools)

            ai_tools = search_by_package("ai")
            assert len(ai_tools) > 0
            assert all(t.package == "ai" for t in ai_tools)


class TestMergingLogic:
    """Test catalog merging logic."""

    def test_enrich_and_merge(self):
        """Test merging capabilities with legacy tools."""
        capabilities = load_capabilities_yaml()
        legacy_tools = load_tools_catalog_json()
        resources = {}
        containers = load_niwrap_containers()
        mapping = load_niwrap_mapping()

        merged = enrich_and_merge(capabilities, legacy_tools, resources, mapping, containers)

        # Should have enriched capabilities
        assert len(merged) > 0
        assert all(isinstance(t, ToolCapability) for t in merged)

        # Check enrichment worked (container info filled in)
        fsl_container_tools = [
            t for t in merged
            if t.package == "fsl" and t.runtime_kind == "container" and t.container
        ]
        if fsl_container_tools:
            tool = fsl_container_tools[0]
            assert tool.container.image is not None
