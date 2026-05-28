"""Unit tests for capabilities schema validation."""

import json
import re
import pytest
import yaml
from pathlib import Path

try:
    import jsonschema
except ImportError:
    pytest.skip("jsonschema not installed", allow_module_level=True)

from brain_researcher.services.agent.planner.catalog_loader import get_repo_root


class TestSchemaValidation:
    """Test JSON schema validation."""

    @pytest.fixture
    def schema(self):
        """Load capabilities schema."""
        repo_root = get_repo_root()
        schema_path = repo_root / "configs" / "schemas" / "capabilities.schema.json"
        with schema_path.open("r") as f:
            return json.load(f)

    @pytest.fixture
    def capabilities_data(self):
        """Load capabilities catalog data."""
        repo_root = get_repo_root()
        capabilities_path = repo_root / "configs" / "catalog" / "capabilities.yaml"
        with capabilities_path.open("r") as f:
            return yaml.safe_load(f)

    def test_schema_is_valid(self, schema):
        """Test that the schema itself is valid JSON Schema."""
        # This will raise if schema is invalid
        jsonschema.Draft7Validator.check_schema(schema)

    def test_capabilities_yaml_validates_against_schema(
        self, capabilities_data, schema
    ):
        """Test that capabilities.yaml validates against the schema."""
        # Create resolver for local file references
        repo_root = get_repo_root()
        schema_path = repo_root / "configs" / "schemas" / "capabilities.schema.json"
        resources_schema_path = repo_root / "configs" / "schemas" / "resources.schema.json"

        # Load referenced schemas
        referenced_schemas = {}
        if resources_schema_path.exists():
            with resources_schema_path.open("r") as f:
                referenced_schemas["resources.schema.json"] = json.load(f)

        # Create custom resolver
        resolver = jsonschema.RefResolver(
            base_uri=schema_path.as_uri(),
            referrer=schema,
            store=referenced_schemas
        )

        # Validate with resolver
        validator = jsonschema.Draft7Validator(schema, resolver=resolver)
        validator.validate(capabilities_data)

    def test_required_fields_present(self, capabilities_data):
        """Test that all required top-level fields are present."""
        assert "version" in capabilities_data
        assert "tools" in capabilities_data
        assert isinstance(capabilities_data["tools"], list)
        assert len(capabilities_data["tools"]) > 0

    def test_tool_entries_have_required_fields(self, capabilities_data):
        """Test that all tool entries have required fields."""
        # Core required fields for all tools
        required_fields = [
            "id",
            "name",
            "package",
            "runtime_kind",
            "modality",
            "capabilities",
            "consumes",
            "produces",
            "resources",
        ]

        for tool in capabilities_data["tools"]:
            for field in required_fields:
                assert field in tool, f"Tool {tool.get('id', 'unknown')} missing {field}"

            # Runtime-specific required fields
            if tool["runtime_kind"] == "container":
                assert "entrypoint" in tool, f"Container tool {tool['id']} missing entrypoint"
                assert "container" in tool, f"Container tool {tool['id']} missing container"

    def test_tool_id_format(self, capabilities_data):
        """Test that tool IDs follow the expected format."""
        for tool in capabilities_data["tools"]:
            tool_id = tool["id"]
            # Should be like "fsl.bet.run" or runtime singleton IDs such as
            # "code_agent" and "ibl_one".
            assert re.match(
                r"^[a-z0-9]+(?:[._][a-z0-9_]+)*$",
                tool_id,
            ), f"Tool ID {tool_id} should use lowercase dot/underscore segments"

    def test_modality_values(self, capabilities_data):
        """Test that modality values are from valid enum."""
        # Keep in sync with models.Modality Literal + capabilities schema
        valid_modalities = {
            "fmri",
            "smri",
            "dmri",
            "eeg",
            "meg",
            "ieeg",
            "pet",
            "genetics",
            "multimodal",
            "optical",
            "clinical",
            "general",
            "literature",
            "data_catalog",
            "rag",
            "search",
        }

        for tool in capabilities_data["tools"]:
            for modality in tool["modality"]:
                assert (
                    modality in valid_modalities
                ), f"Invalid modality {modality} in tool {tool['id']}"

    def test_resource_spec_valid(self, capabilities_data):
        """Test that resource specifications are valid."""
        for tool in capabilities_data["tools"]:
            resources = tool["resources"]
            assert "cpu_min" in resources
            assert "mem_mb_min" in resources
            assert "gpu" in resources
            assert "time_min_default" in resources

            # Check ranges
            assert 1 <= resources["cpu_min"] <= 32
            assert 128 <= resources["mem_mb_min"] <= 131072
            assert isinstance(resources["gpu"], bool)
            assert 0 <= resources["time_min_default"] <= 2880

    def test_container_spec_valid(self, capabilities_data):
        """Test that container specifications are valid."""
        valid_runtimes = {"apptainer", "singularity", "docker"}

        for tool in capabilities_data["tools"]:
            if tool.get("runtime_kind") != "container":
                continue
            container = tool.get("container") or {}
            assert "package_ref" in container
            assert "runtime" in container
            assert (
                container["runtime"] in valid_runtimes
            ), f"Invalid runtime {container['runtime']} in tool {tool['id']}"

    def test_consumes_produces_types(self, capabilities_data):
        """Test that consumes/produces use valid resource types."""
        from brain_researcher.services.shared.planner.models import ResourceType

        valid_types = ResourceType.get_allowed()

        for tool in capabilities_data["tools"]:
            for resource_type in tool["consumes"]:
                assert (
                    resource_type in valid_types
                ), f"Invalid consumes type {resource_type} in tool {tool['id']}"

            for resource_type in tool["produces"]:
                assert (
                    resource_type in valid_types
                ), f"Invalid produces type {resource_type} in tool {tool['id']}"

    def test_no_duplicate_tool_ids(self, capabilities_data):
        """Test that tool IDs are unique."""
        tool_ids = [tool["id"] for tool in capabilities_data["tools"]]
        assert len(tool_ids) == len(
            set(tool_ids)
        ), "Duplicate tool IDs found in catalog"

    def test_package_consistency(self, capabilities_data):
        """Test that package field is consistent with tool ID."""
        for tool in capabilities_data["tools"]:
            tool_id = tool["id"]
            package = tool["package"]
            if tool_id.startswith("container."):
                continue
            # Tool ID should start with package name
            assert tool_id.startswith(
                package + "."
            ) or tool_id.startswith(f"{package}_"), f"Tool ID {tool_id} doesn't start with package {package}"

    def test_metadata_optional_but_valid(self, capabilities_data):
        """Test that metadata, if present, is valid."""
        for tool in capabilities_data["tools"]:
            if "metadata" in tool:
                metadata = tool["metadata"] or {}
                # If present, allow empty dict (common for generated/curated stubs)
                if "description" in metadata:
                    assert isinstance(metadata["description"], str)
                if "authors" in metadata:
                    assert isinstance(metadata["authors"], list)
                if "literature" in metadata:
                    assert isinstance(metadata["literature"], list)
                if "urls" in metadata:
                    assert isinstance(metadata["urls"], list)


class TestContractConsistency:
    """Test consistency between capabilities.yaml and other configs."""

    def test_packages_exist_in_niwrap_containers(self):
        """Test that package_ref values exist in niwrap_containers.yaml."""
        from brain_researcher.services.agent.planner.catalog_loader import (
            load_capabilities_yaml,
            load_niwrap_containers,
        )

        tools = load_capabilities_yaml()
        containers = load_niwrap_containers()

        for tool in tools:
            if tool.runtime_kind != "container" or tool.container is None:
                continue
            package_ref = tool.container.package_ref
            # Some package_refs might not be in containers (optional)
            # But if they're common packages, they should be there
            if package_ref in ["fsl", "ants", "afni", "freesurfer", "mrtrix"]:
                assert (
                    package_ref in containers
                ), f"Package {package_ref} not found in niwrap_containers.yaml"

    def test_tool_ids_follow_entrypoint_pattern(self):
        """Test that tool IDs roughly match entrypoints."""
        from brain_researcher.services.agent.planner.catalog_loader import (
            load_capabilities_yaml,
        )

        tools = load_capabilities_yaml()

        for tool in tools:
            # Tool ID should be related to entrypoint
            # e.g., fsl.bet.run should have entrypoint like fsl.6.0.7.bet.run
            if tool.id.startswith("container."):
                # container.* ids wrap niwrap tool names; skip strict check
                continue
            if not tool.entrypoint:
                continue
            tool_parts = tool.id.split(".")
            entrypoint_parts = tool.entrypoint.split(".")

            # Package should match or be a prefix (e.g., mrtrix vs mrtrix3)
            package_from_id = tool_parts[0]
            package_from_entrypoint = entrypoint_parts[0]

            # Allow flexible matching - either exact or one is prefix of other
            is_match = (
                package_from_id == package_from_entrypoint
                or package_from_id.startswith(package_from_entrypoint)
                or package_from_entrypoint.startswith(package_from_id)
            )

            assert is_match, (
                f"Package mismatch: {tool.id} vs {tool.entrypoint}"
            )


class TestResourceTypeValidation:
    """Test runtime validation of resource types against tool_resources.yaml."""

    def test_invalid_resource_type_rejected(self, tmp_path):
        """Test that tools with invalid resource types are rejected by validator."""
        import subprocess
        import sys

        # Create a test capabilities file with an invalid resource type
        test_capabilities = {
            "version": "0.1.0",
            "tools": [
                {
                    "id": "test.invalid_resource.run",
                    "name": "Test Tool with Invalid Resource",
                    "package": "test",
                    "runtime_kind": "container",
                    "entrypoint": "test.1.0.invalid.run",
                    "modality": ["fmri"],
                    "capabilities": ["test_capability"],
                    "consumes": ["invalid_resource_type_xyz"],  # This doesn't exist in resources.schema.json
                    "produces": ["volume_3d"],
                    "resources": {
                        "cpu_min": 1,
                        "mem_mb_min": 512,
                        "gpu": False,
                        "time_min_default": 5.0,
                    },
                    "container": {
                        "package_ref": "test",
                        "runtime": "apptainer"
                    }
                }
            ]
        }

        # Write test file
        test_file = tmp_path / "test_capabilities.yaml"
        with test_file.open("w") as f:
            yaml.dump(test_capabilities, f)

        # Import and test the validator function directly
        from scripts.ci.validate_capabilities import validate_resource_types

        # Should fail because "invalid_resource_type_xyz" is not in resources.schema.json
        success, errors = validate_resource_types(test_file)

        assert not success, "Validation should fail for invalid resource type"
        assert len(errors) > 0, "Should have error messages"
        assert any("invalid_resource_type_xyz" in str(error) for error in errors), \
            "Error should mention the invalid resource type"

    def test_valid_resource_types_accepted(self, tmp_path):
        """Test that tools with valid resource types pass validation."""
        # Create a test capabilities file with valid resource types
        test_capabilities = {
            "version": "0.1.0",
            "tools": [
                {
                    "id": "test.valid_resource.run",
                    "name": "Test Tool with Valid Resources",
                    "package": "test",
                    "runtime_kind": "container",
                    "entrypoint": "test.1.0.valid.run",
                    "modality": ["fmri"],
                    "capabilities": ["test_capability"],
                    "consumes": ["volume_4d", "mask_path"],  # These exist in resources.schema.json
                    "produces": ["stat_map", "volume_3d"],  # These exist too
                    "resources": {
                        "cpu_min": 1,
                        "mem_mb_min": 512,
                        "gpu": False,
                        "time_min_default": 5.0,
                    },
                    "container": {
                        "package_ref": "test",
                        "runtime": "apptainer"
                    }
                }
            ]
        }

        # Write test file
        test_file = tmp_path / "test_capabilities.yaml"
        with test_file.open("w") as f:
            yaml.dump(test_capabilities, f)

        # Import and test the validator function directly
        from scripts.ci.validate_capabilities import validate_resource_types

        # Should pass because all resource types are valid
        success, errors = validate_resource_types(test_file)

        assert success, f"Validation should pass for valid resource types. Errors: {errors}"
